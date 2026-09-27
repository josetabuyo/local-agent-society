import test from 'node:test';
import assert from 'node:assert/strict';
import { Pipeline, CONTINUE, HANDLED, dedupInterceptor, ignoreKindsInterceptor, senderPolicyInterceptor, micSelfTestInterceptor, httpInterceptor } from '../src/pipeline.js';
import { normalize, MIC_SELFTEST_PING, KIND } from '../src/envelope.js';

const ctxFor = (env, extra = {}) => ({ envelope: normalize(env), agent: 'Me', log: () => {}, reply: async () => {}, publish: async () => {}, ...extra });

test('interceptors run in order and a HANDLED verdict short-circuits the rest', async () => {
  const calls = [];
  const p = new Pipeline([
    { name: 'a', handle: () => (calls.push('a'), CONTINUE) },
    { name: 'b', handle: () => (calls.push('b'), HANDLED) },
    { name: 'c', handle: () => (calls.push('c'), CONTINUE) },
  ]);
  assert.deepEqual(await p.run(ctxFor({ text: 'x' })), { handledBy: 'b' });
  assert.deepEqual(calls, ['a', 'b']);
  assert.deepEqual(await new Pipeline([]).run(ctxFor({ text: 'x' })), { handledBy: null });
  assert.throws(() => new Pipeline([{ name: 'bad' }]), TypeError);
});

test('dedup drops a repeated id (at-least-once redelivery) and forgets beyond its window', async () => {
  const d = dedupInterceptor({ size: 2 });
  assert.equal(await d.handle(ctxFor({ id: '1', text: 'a' })), CONTINUE);
  assert.equal(await d.handle(ctxFor({ id: '1', text: 'a' })), HANDLED);
  assert.equal(await d.handle(ctxFor({ id: '2', text: 'b' })), CONTINUE);
  assert.equal(await d.handle(ctxFor({ id: '3', text: 'c' })), CONTINUE);
  assert.equal(await d.handle(ctxFor({ id: '1', text: 'a' })), CONTINUE, 'evicted after the window');
});

test('ignore-kinds and sender-policy swallow exactly what they are told to', async () => {
  const ig = ignoreKindsInterceptor([KIND.MIC_SELFTEST_PONG]);
  assert.equal(await ig.handle(ctxFor({ kind: KIND.MIC_SELFTEST_PONG, text: 'OK' })), HANDLED);
  assert.equal(await ig.handle(ctxFor({ text: 'hello' })), CONTINUE);
  const dropped = [];
  const sp = senderPolicyInterceptor({ allow: (e) => e.from !== 'Evil', log: (m) => dropped.push(m) });
  assert.equal(await sp.handle(ctxFor({ from: 'Evil', text: 'rm -rf' })), HANDLED);
  assert.equal(await sp.handle(ctxFor({ from: 'Friend', text: 'hi' })), CONTINUE);
  assert.equal(dropped.length, 1);
});

test('mic self-test: pongs on the agent inbox silently and STILL passes the ping on (a session may add its audible OK)', async () => {
  const published = [];
  const i = micSelfTestInterceptor({ agent: 'Me', now: () => 7 });
  const verdict = await i.handle(ctxFor({ from: 'Me', to: 'Me', text: MIC_SELFTEST_PING, source: 'human' }, { publish: async (t, o) => published.push([t, o]) }));
  assert.equal(verdict, CONTINUE);
  assert.deepEqual(published, [['las/agent/Me/inbox', { from: 'Me', to: 'Me', source: 'system', kind: KIND.MIC_SELFTEST_PONG, text: 'OK', ts: 7 }]]);
  assert.equal(await i.handle(ctxFor({ text: 'not a ping' }, { publish: async () => assert.fail('must not publish') })), CONTINUE);
});

test('http interceptor obeys handled/continue+rewrite and FAILS OPEN on any error', async () => {
  const fake = (body) => async () => ({ ok: true, json: async () => body });
  const h1 = httpInterceptor({ url: 'http://x/decide', fetchImpl: fake({ action: 'handled' }) });
  assert.equal(await h1.handle(ctxFor({ text: 'noise' })), HANDLED);
  const ctx = ctxFor({ text: 'abrir la terminal' });
  const h2 = httpInterceptor({ url: 'http://x/decide', fetchImpl: fake({ action: 'continue', envelope: { text: 'open the terminal', kind: 'command' } }) });
  assert.equal(await h2.handle(ctx), CONTINUE);
  assert.equal(ctx.envelope.text, 'open the terminal');
  assert.equal(ctx.envelope.kind, 'command');
  const logs = [];
  const down = httpInterceptor({ url: 'http://x/decide', fetchImpl: async () => { throw new Error('ECONNREFUSED'); }, log: (m) => logs.push(m) });
  const ctx2 = ctxFor({ text: 'keep me' });
  assert.equal(await down.handle(ctx2), CONTINUE);
  assert.equal(ctx2.envelope.text, 'keep me');
  assert.match(logs[0], /failed open/);
  const bad = httpInterceptor({ url: 'http://x/decide', fetchImpl: async () => ({ ok: false, status: 500 }) });
  assert.equal(await bad.handle(ctxFor({ text: 'x' })), CONTINUE);
  assert.throws(() => httpInterceptor({}), TypeError);
});
