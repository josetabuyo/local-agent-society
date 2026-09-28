/**
 * MailboxSource — THE consumer of one agent's vortexia mailbox.
 *
 * Connects with the agent's fixed mailbox client id and a persistent
 * session (vortexia/PROTOCOL.md "Mailboxes"): on connect the broker hands
 * over everything queued while nobody was listening, in order, then live
 * traffic. Each message is consumed by its QoS 1 ack — and this class sends
 * that ack only AFTER `deliver(envelope)` resolved (mqtt.js's
 * handleMessage hook: the puback goes out when its callback runs). If
 * delivery rejects, the connection is dropped instead: an unacked QoS 1
 * message stays in the session and the broker redelivers it on reconnect,
 * so a sink that failed mid-message costs a retry, never the message.
 *
 * Only one connection can hold the session. A rival with the same client
 * id kicks this one; if reconnected connections die within seconds three
 * times in a row (connection *lifetime*, not wall-clock spacing — a Mac
 * that slept jumps the clock) it's a takeover fight and 'takeover' is
 * emitted instead of fighting forever. A drop after a full keep-alive
 * period is ordinary (sleep, broker restart) and just reconnects.
 */
import { EventEmitter } from 'node:events';
import mqtt from 'mqtt';
import { resolveMqttPort } from './port.js';

export function inboxTopic(agent) {
  return `las/agent/${agent}/inbox`;
}

export function mailboxClientId(agent) {
  return `las-agent-${agent}`;
}

export class MailboxSource extends EventEmitter {
  constructor({
    agent,
    topic,
    clientId,
    host = 'localhost',
    port,
    connect = mqtt.connect,
    log = () => {},
    fightDrops = 3,
    fightLifetimeMs = 15_000,
    redeliverDelayMs = 5_000,
    now = () => performance.now(),
  }) {
    super();
    if (!agent) throw new TypeError('MailboxSource needs an agent name');
    this.agent = agent;
    this._topic = topic || inboxTopic(agent);
    this._clientId = clientId || mailboxClientId(agent);
    this.host = host;
    this.port = port;
    this.connect = connect;
    this.log = log;
    this.fightDrops = fightDrops;
    this.fightLifetimeMs = fightLifetimeMs;
    this.redeliverDelayMs = redeliverDelayMs;
    this.now = now;
    this.client = null;
    this.stopped = false;
    this.connectedAt = 0;
    this.shortLived = 0;
  }

  /** The inbox this source consumes: the agent's, or one session's (see sessions.js). */
  get topic() {
    return this._topic;
  }

  get clientId() {
    return this._clientId;
  }

  /** Start consuming; `deliver(envelope)` must resolve once the message is safely handed over. */
  async start(deliver) {
    if (typeof deliver !== 'function') throw new TypeError('start(deliver) needs a function');
    this.deliver = deliver;
    this.stopped = false;
    const port = await resolveMqttPort({ explicit: this.port });
    const client = this.connect(`mqtt://${this.host}:${port}`, {
      clientId: this._clientId,
      clean: false,
      protocolVersion: 4,
      keepalive: 30,
      reconnectPeriod: 2000,
      // We subscribe ourselves on every 'connect' (see below); mqtt.js's own
      // resubscribe would only duplicate that.
      resubscribe: false,
    });
    this.client = client;

    client.handleMessage = (packet, done) => this._onPacket(packet, done);

    client.on('connect', (connack) => {
      this.connectedAt = this.now();
      const sessionPresent = Boolean(connack && connack.sessionPresent);
      // Always (re)subscribe, even when the broker reports the session as
      // present. Subscribing is idempotent for a persistent session, and
      // seen live on 2026-09-28: a mailbox session restored by the broker
      // reported sessionPresent yet delivered nothing — neither its backlog
      // nor live publishes — until a client subscribed the inbox again.
      // (The old "only subscribe on a new session" rule guarded against a
      // legacy retained message replaying; the backend stopped retaining
      // inbox traffic long ago, so that guard costs more than it saves.)
      client.subscribe(this.topic, { qos: 1 });
      this.emit('connect', { sessionPresent, port });
    });

    client.on('close', () => {
      if (this.stopped) return;
      const lived = this.now() - this.connectedAt;
      this.shortLived = lived < this.fightLifetimeMs ? this.shortLived + 1 : 0;
      if (this.shortLived >= this.fightDrops) {
        this.log(`${this.agent}: mailbox session lost ${this.fightDrops} times in a row within seconds of connecting — another consumer keeps taking it over, giving up`);
        this.stopped = true;
        client.end(true);
        this.emit('takeover');
        return;
      }
      this.log(`${this.agent}: connection dropped after ${Math.round(lived / 1000)}s — reconnecting, mailbox session kept by the broker`);
      this.emit('reconnect', { lived });
    });

    // mqtt.js throws if 'error' has no listener; a refused connection is
    // reported and then retried by reconnectPeriod, it must not crash us.
    client.on('error', (err) => {
      this.log(`${this.agent}: mqtt error: ${err && err.message ? err.message : err}`);
      this.emit('error-soft', err);
    });

    return this;
  }

  _onPacket(packet, done) {
    if (packet.topic !== this.topic) return done();
    let envelope;
    try {
      envelope = JSON.parse(packet.payload.toString('utf8'));
    } catch {
      return done(); // not an envelope — ack and forget, same as listen
    }
    Promise.resolve()
      .then(() => this.deliver(envelope))
      .then(
        () => done(), // -> puback: consumed
        (err) => {
          this.log(`${this.agent}: delivery failed (${err && err.message ? err.message : err}) — dropping the connection so the broker redelivers`);
          this.emit('deliver-error', err);
          // Do NOT call done(): the message stays unacked in the session.
          this.client.end(true);
          if (!this.stopped) {
            const timer = setTimeout(() => {
              if (!this.stopped) this.start(this.deliver).catch((e) => this.emit('error-soft', e));
            }, this.redeliverDelayMs);
            timer.unref?.();
          }
        },
      );
  }

  /** Publish an envelope (QoS 1) on any topic — used for the mic self-test pong. */
  publish(topic, obj) {
    return new Promise((resolve, reject) => {
      if (!this.client) return reject(new Error('not connected'));
      this.client.publish(topic, JSON.stringify(obj), { qos: 1, retain: false }, (err) => (err ? reject(err) : resolve()));
    });
  }

  /** Clean disconnect: the session (and anything unacked) stays on the broker. */
  async stop() {
    this.stopped = true;
    const client = this.client;
    this.client = null;
    if (!client) return;
    await new Promise((resolve) => client.end(false, {}, () => resolve()));
  }
}
