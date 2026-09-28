import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { MailboxSource, inboxTopic, mailboxClientId } from '../src/source.js';

/** Minimal mqtt.js stand-in: records subscribe/publish/end, lets a test push packets through handleMessage. */
function fakeMqtt() {
  const clients = [];
  const connect = (url, options) => {
    const c = new EventEmitter();
    c.url = url;
    c.options = options;
    c.subscribed = [];
    c.published = [];
    c.ended = [];
    c.subscribe = (t, o) => c.subscribed.push([t, o]);
    c.publish = (t, p, o, cb) => { c.published.push([t, p, o]); cb && cb(); };
    c.end = (force, o, cb) => { c.ended.push(force); cb && cb(); };
    c.handleMessage = (p, cb) => cb();
    clients.push(c);
    return c;
  };
  return { connect, clients };
}

const packet = (topic, obj) => ({ topic, payload: Buffer.from(JSON.stringify(obj)) });
const tick = () => new Promise((r) => setImmediate(r));

test('connects as the mailbox consumer (fixed client id, persistent session) and subscribes on every connect', async () => {
  const { connect, clients } = fakeMqtt();
  const src = new MailboxSource({ agent: 'Robo', port: 1999, connect });
  await src.start(async () => {});
  const c = clients[0];
  assert.equal(c.url, 'mqtt://localhost:1999');
  assert.equal(c.options.clientId, mailboxClientId('Robo'));
  assert.equal(c.options.clean, false);
  assert.equal(c.options.resubscribe, false);
  c.emit('connect', { sessionPresent: true });
  assert.deepEqual(c.subscribed, [[inboxTopic('Robo'), { qos: 1 }]], 'a resumed session is re-subscribed anyway (idempotent; a restored session was seen delivering nothing until then)');
  c.emit('connect', { sessionPresent: false });
  assert.deepEqual(c.subscribed, [[inboxTopic('Robo'), { qos: 1 }], [inboxTopic('Robo'), { qos: 1 }]]);
});

test('acks (calls done) only AFTER deliver resolved; drops the connection and does not ack when deliver rejects', async () => {
  const { connect, clients } = fakeMqtt();
  let resolveDeliver;
  const delivered = [];
  const src = new MailboxSource({ agent: 'Robo', port: 1, connect, redeliverDelayMs: 1 });
  await src.start((env) => new Promise((resolve) => { delivered.push(env); resolveDeliver = resolve; }));
  const c = clients[0];
  let acked = 0;
  c.handleMessage(packet(inboxTopic('Robo'), { from: 'A', text: 'hi' }), () => acked++);
  await tick();
  assert.equal(delivered.length, 1);
  assert.equal(acked, 0, 'no puback while the sink is still working');
  resolveDeliver();
  await tick();
  assert.equal(acked, 1);

  // other topics and junk payloads are acked without delivering
  c.handleMessage(packet('las/broadcast', { text: 'x' }), () => acked++);
  c.handleMessage({ topic: inboxTopic('Robo'), payload: Buffer.from('not json') }, () => acked++);
  assert.equal(acked, 3);
  assert.equal(delivered.length, 1);

  // a failing sink: no ack, connection ended (broker keeps the unacked message), reconnect scheduled
  const failing = new MailboxSource({ agent: 'Robo', port: 1, connect, redeliverDelayMs: 1 });
  await failing.start(async () => { throw new Error('sink down'); });
  const c2 = clients[1];
  const errors = [];
  failing.on('deliver-error', (e) => errors.push(e.message));
  let acked2 = 0;
  c2.handleMessage(packet(inboxTopic('Robo'), { from: 'A', text: 'hi' }), () => acked2++);
  await tick();
  assert.equal(acked2, 0);
  assert.deepEqual(c2.ended, [true]);
  assert.deepEqual(errors, ['sink down']);
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(clients.length, 3, 'a fresh connection was opened so the broker can redeliver');
  await failing.stop();
});

test('a takeover fight (3 drops within seconds of connecting) emits takeover; a long-lived connection dropping is just a reconnect', async () => {
  const { connect, clients } = fakeMqtt();
  let t = 0;
  const src = new MailboxSource({ agent: 'Robo', port: 1, connect, now: () => t, fightLifetimeMs: 15000 });
  await src.start(async () => {});
  const c = clients[0];
  const events = [];
  src.on('reconnect', () => events.push('reconnect'));
  src.on('takeover', () => events.push('takeover'));
  c.emit('connect', { sessionPresent: true }); t += 60000; c.emit('close');   // ordinary keep-alive drop
  c.emit('connect', { sessionPresent: true }); t += 1000; c.emit('close');    // short 1
  c.emit('connect', { sessionPresent: true }); t += 1000; c.emit('close');    // short 2
  c.emit('connect', { sessionPresent: true }); t += 1000; c.emit('close');    // short 3 -> fight
  assert.deepEqual(events, ['reconnect', 'reconnect', 'reconnect', 'takeover']);
  assert.deepEqual(c.ended, [true]);
  c.emit('close');
  assert.equal(events.length, 4, 'nothing more once stopped');
});

test('publish is QoS 1, not retained; stop ends cleanly (session kept)', async () => {
  const { connect, clients } = fakeMqtt();
  const src = new MailboxSource({ agent: 'Robo', port: 1, connect });
  await src.start(async () => {});
  await src.publish('las/agent/Robo/inbox', { text: 'OK' });
  assert.deepEqual(clients[0].published, [['las/agent/Robo/inbox', '{"text":"OK"}', { qos: 1, retain: false }]]);
  await src.stop();
  assert.deepEqual(clients[0].ended, [false]);
  await assert.rejects(src.publish('t', {}), /not connected/);
});
