/**
 * Bridge — composes one MailboxSource, one Pipeline and one Sink. The only
 * place that knows the order of operations:
 *   1. start the sink (a channel sink opens its MCP transport)
 *   2. if the sink must be ARMED (proven end-to-end), wait for that
 *   3. only then attach the mailbox — nothing is consumed before there is
 *      somewhere proven to put it
 *   4. per message: normalize -> interceptors -> sink -> ack (the source
 *      acks when `handle` resolves)
 */
import { normalize } from './envelope.js';

export class Bridge {
  /**
   * `source` is the agent-level mailbox source. With `session` (a
   * SessionRegistry) and `sessionSource` (this session's own inbox) and
   * `defaultWatcher`, the bridge runs as ONE SESSION of the agent: its own
   * inbox is always consumed; the agent mailbox only while the backend says
   * this session is the default (last used) — see sessions.js.
   */
  constructor({ agent, source, pipeline, sink, send, status = null, log = () => {}, session = null, sessionSource = null, defaultWatcher = null, attachDelayMs = 400 }) {
    if (!agent || !source || !pipeline || !sink) throw new TypeError('Bridge needs agent, source, pipeline and sink');
    this.agent = agent;
    this.source = source;
    this.pipeline = pipeline;
    this.sink = sink;
    this.send = send;
    this.status = status;
    this.log = log;
    this.session = session;
    this.sessionSource = sessionSource;
    this.defaultWatcher = defaultWatcher;
    this.attachDelayMs = attachDelayMs;
    this.isDefault = false;
    this.agentAttached = false;
    this._attachTimer = null;
  }

  async run() {
    if (typeof this.sink.start === 'function') await this.sink.start();
    if (typeof this.sink.waitArmed === 'function') {
      this.status?.update({ armed: false });
      await this.sink.waitArmed();
    }
    this.status?.update({ armed: true });
    const deliver = (envelope) => this.handle(envelope);
    if (this.session && this.sessionSource && this.defaultWatcher) {
      // Session mode: own inbox first, then announce ourselves (which makes
      // us the default) and let the watcher decide about the agent mailbox.
      await this.sessionSource.start(deliver);
      this.defaultWatcher.on('default', (sid) => this._onDefault(sid, deliver));
      await this.defaultWatcher.start();
      const view = await this.session.register();
      this.status?.update({ sid: this.session.sid, runtime: this.session.runtime, registered: Boolean(view) });
      if (!view) {
        // Backend down: nobody can elect a default, so behave like the old
        // single-consumer bridge and hold the agent mailbox ourselves.
        this.log(`${this.agent}: backend unreachable — holding the agent mailbox without a default election`);
        this._onDefault(this.session.sid, deliver);
      }
      return this;
    }
    await this.source.start(deliver);
    this.agentAttached = true;
    return this;
  }

  _onDefault(sid, deliver) {
    const mine = Boolean(sid) && sid === this.session.sid;
    if (mine === this.isDefault) return;
    this.isDefault = mine;
    this.status?.update({ default: mine });
    clearTimeout(this._attachTimer);
    if (mine) {
      // Give the previous default a moment to release the agent mailbox
      // before we take it — it sees the same retained update we just did.
      this._attachTimer = setTimeout(() => {
        if (!this.isDefault || this.agentAttached) return;
        this.agentAttached = true;
        this.log(`${this.agent}: this session (${sid}) is now the default — holding the agent mailbox`);
        this.source.start(deliver).catch((err) => this.log(`${this.agent}: agent mailbox attach failed: ${err && err.message ? err.message : err}`));
      }, this.attachDelayMs);
      this._attachTimer.unref?.();
    } else if (this.agentAttached) {
      this.agentAttached = false;
      this.log(`${this.agent}: another session (${sid || 'none'}) is the default — releasing the agent mailbox`);
      this.source.stop().catch(() => {});
    }
  }

  async handle(raw) {
    const envelope = normalize(raw);
    const ctx = {
      envelope,
      agent: this.agent,
      log: this.log,
      reply: (text) => {
        if (!this.send) throw new Error('no sender configured');
        return this.send(envelope.from, text);
      },
      publish: (topic, obj) => this.source.publish(topic, obj),
    };
    const { handledBy } = await this.pipeline.run(ctx);
    if (handledBy) {
      this.log(`${this.agent}: ${ctx.envelope.kind} from ${ctx.envelope.from} handled by ${handledBy}`);
      return { handledBy };
    }
    await this.sink.deliver(ctx);
    this.status?.bump();
    if (this.session) this.session.touch(); // activity: this session is the one being used
    return { handledBy: null };
  }

  async stop() {
    clearTimeout(this._attachTimer);
    if (this.session) await this.session.unregister();
    if (this.defaultWatcher) await this.defaultWatcher.stop();
    if (this.sessionSource) await this.sessionSource.stop();
    await this.source.stop();
    if (typeof this.sink.stop === 'function') await this.sink.stop();
    this.status?.remove();
  }
}
