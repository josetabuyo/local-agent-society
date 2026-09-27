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
  constructor({ agent, source, pipeline, sink, send, status = null, log = () => {} }) {
    if (!agent || !source || !pipeline || !sink) throw new TypeError('Bridge needs agent, source, pipeline and sink');
    this.agent = agent;
    this.source = source;
    this.pipeline = pipeline;
    this.sink = sink;
    this.send = send;
    this.status = status;
    this.log = log;
  }

  async run() {
    if (typeof this.sink.start === 'function') await this.sink.start();
    if (typeof this.sink.waitArmed === 'function') {
      this.status?.update({ armed: false });
      await this.sink.waitArmed();
    }
    this.status?.update({ armed: true });
    await this.source.start((envelope) => this.handle(envelope));
    return this;
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
    return { handledBy: null };
  }

  async stop() {
    await this.source.stop();
    if (typeof this.sink.stop === 'function') await this.sink.stop();
    this.status?.remove();
  }
}
