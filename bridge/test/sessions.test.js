import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { SessionRegistry, DefaultWatcher, newSessionId, sessionInboxTopic, sessionMailboxClientId, defaultSessionTopic } from '../src/sessions.js';
import { Bridge } from '../src/bridge.js';
import { Pipeline } from '../src/pipeline.js';
import { MailboxSource } from '../src/source.js';

const tick = () => new Promise((r) => setImmediate(r));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

test('session ids and topics are per agent + session; the agent mailbox stays what it was', () => {
  const sid = newSessionId('claude', { pid: 42, randomId: () => 'abc' });
  assert.equal(sid, 'claude-42-abc');
  assert.equal(sessionInboxTopic('Robo', sid), 'las/agent/Robo/sessions/claude-42-abc/inbox');
  assert.equal(sessionMailboxClientId('Robo', sid), 'las-agent-Robo-claude-42-abc');
  assert.equal(defaultSessionTopic('Robo'), 'las/agent/Robo/default-session');
  const own = new MailboxSource({ agent: 'Robo', topic: sessionInboxTopic('Robo', sid), clientId: sessionMailboxClientId('Robo', sid) });
  assert.equal(own.topic, 'las/agent/Robo/sessions/claude-42-abc/inbox');
  assert.equal(own.clientId, 'las-agent-Robo-claude-42-abc');
  const agentLevel = new MailboxSource({ agent: 'Robo' });
  assert.equal(agentLevel.topic, 'las/agent/Robo/inbox');
  assert.equal(agentLevel.clientId, 'las-agent-Robo');
});

test('SessionRegistry talks to the backend session endpoints and fails soft', async () => {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push([init.method, url, init.body && JSON.parse(init.body)]); return { ok: true, json: async () => ({ default: 'x' }) }; };
  const reg = new SessionRegistry({ agent: 'Robo', sid: 'claude-1-a', runtime: 'claude', cwd: '/x', pid: 7, fetchImpl, registryUrl: 'http://b' });
  assert.deepEqual(await reg.register(), { default: 'x' });
  await reg.touch();
  await reg.unregister();
  assert.deepEqual(calls, [
    ['POST', 'http://b/agents/Robo/sessions', { sid: 'claude-1-a', runtime: 'claude', pid: 7, cwd: '/x' }],
    ['POST', 'http://b/agents/Robo/sessions/claude-1-a/touch', undefined],
    ['DELETE', 'http://b/agents/Robo/sessions/claude-1-a', undefined],
  ]);
  const down = new SessionRegistry({ agent: 'Robo', sid: 's', runtime: 'shell', fetchImpl: async () => { throw new Error('ECONNREFUSED'); } });
  assert.equal(await down.register(), null);
  const notFound = new SessionRegistry({ agent: 'Robo', sid: 's', runtime: 'shell', fetchImpl: async () => ({ ok: false, status: 404 }) });
  assert.equal(await notFound.touch(), null);
});

test('DefaultWatcher emits the retained default sid, only on change, null for none/garbage', async () => {
  let client;
  const connect = () => { client = new EventEmitter(); client.subscribed = []; client.subscribe = (t) => client.subscribed.push(t); client.end = (f, o, cb) => cb(); return client; };
  const w = new DefaultWatcher({ agent: 'Robo', port: 1, connect });
  const seen = [];
  w.on('default', (sid) => seen.push(sid));
  await w.start();
  client.emit('connect');
  assert.deepEqual(client.subscribed, ['las/agent/Robo/default-session']);
  const msg = (obj) => client.emit('message', 'las/agent/Robo/default-session', Buffer.from(typeof obj === 'string' ? obj : JSON.stringify(obj)));
  msg({ sid: 'claude-1' });
  msg({ sid: 'claude-1' });
  msg({ sid: 'shell-2' });
  msg({ sid: null });
  msg('garbage');
  client.emit('message', 'las/agent/Other/default-session', Buffer.from('{"sid":"x"}'));
  assert.deepEqual(seen, ['claude-1', 'shell-2', null]);
  await w.stop();
});

function fakeSource(name, order) {
  return { name, started: 0, stopped: 0, start: async () => { order.push(`${name}.start`); }, stop: async () => { order.push(`${name}.stop`); }, publish: async () => {} };
}

test('session mode: own inbox first, register, hold the agent mailbox only while default, release when another session takes it', async () => {
  const order = [];
  const agentSource = fakeSource('agent', order);
  const sessionSource = fakeSource('session', order);
  const watcher = new EventEmitter();
  watcher.start = async () => order.push('watcher.start');
  watcher.stop = async () => order.push('watcher.stop');
  const registry = { sid: 'claude-1', runtime: 'claude', register: async () => (order.push('register'), { default: 'claude-1' }), touch: async () => order.push('touch'), unregister: async () => order.push('unregister') };
  const sink = { name: 'fake', deliver: async () => {} };
  const bridge = new Bridge({ agent: 'Robo', source: agentSource, sessionSource, defaultWatcher: watcher, session: registry, pipeline: new Pipeline([]), sink, attachDelayMs: 5 });
  await bridge.run();
  assert.deepEqual(order, ['session.start', 'watcher.start', 'register']);
  assert.equal(bridge.agentAttached, false, 'the agent mailbox waits for the backend to say we are the default');

  watcher.emit('default', 'claude-1');
  await wait(15);
  assert.deepEqual(order.slice(3), ['agent.start']);
  assert.equal(bridge.isDefault, true);

  watcher.emit('default', 'shell-2');
  await tick();
  assert.deepEqual(order.slice(4), ['agent.stop'], 'another session became the default: release, no fight');
  assert.equal(bridge.agentAttached, false);

  watcher.emit('default', 'claude-1');
  watcher.emit('default', 'shell-2');   // flipped back before the attach delay elapsed
  await wait(15);
  assert.deepEqual(order.slice(5), [], 'a default that flips back within the delay never attaches');

  await bridge.handle({ from: 'X', text: 'hi' });
  assert.ok(order.includes('touch'), 'a delivery marks this session as used');

  await bridge.stop();
  assert.deepEqual(order.slice(-5), ['touch', 'unregister', 'watcher.stop', 'session.stop', 'agent.stop']);
});

test('session mode with the backend down: hold the agent mailbox anyway (the old single-consumer behavior)', async () => {
  const order = [];
  const agentSource = fakeSource('agent', order);
  const sessionSource = fakeSource('session', order);
  const watcher = new EventEmitter();
  watcher.start = async () => {};
  watcher.stop = async () => {};
  const registry = { sid: 'shell-9', runtime: 'shell', register: async () => null, touch: async () => null, unregister: async () => null };
  const bridge = new Bridge({ agent: 'Robo', source: agentSource, sessionSource, defaultWatcher: watcher, session: registry, pipeline: new Pipeline([]), sink: { deliver: async () => {} }, attachDelayMs: 1 });
  await bridge.run();
  await wait(10);
  assert.deepEqual(order, ['session.start', 'agent.start']);
  assert.equal(bridge.isDefault, true);
});
