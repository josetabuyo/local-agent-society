import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ProcSink, parseProcLine, procMessageLine } from '../src/sinks/proc.js';

const sink = (over = {}) => {
  const sent = [];
  const titles = [];
  const out = { text: '', write(s) { this.text += s; } };
  const s = new ProcSink({ agent: 'Me', sid: 'x-1', shell: '/bin/sh', out, log: () => {},
    send: async (to, text) => sent.push([to, text]), setTitle: async (t) => titles.push(t), ...over });
  return { s, sent, titles, out };
};
const until = async (fn) => { for (let i = 0; i < 100 && !fn(); i++) await new Promise((r) => setTimeout(r, 20)); };

test('parseProcLine: only reply/title JSON is protocol, everything else is log text', () => {
  assert.deepEqual(parseProcLine('{"type":"reply","text":"hi"}'), { type: 'reply', text: 'hi', to: null });
  assert.deepEqual(parseProcLine('{"type":"reply","to":"Bob","text":"hi"}'), { type: 'reply', text: 'hi', to: 'Bob' });
  assert.deepEqual(parseProcLine('{"type":"title","text":"T"}'), { type: 'title', text: 'T' });
  for (const l of ['plain log', '{"type":"other","text":"x"}', '{broken', '{"type":"reply"}']) assert.equal(parseProcLine(l), null);
});

test('procMessageLine carries just the contract fields', () => {
  const line = procMessageLine({ id: 'i', from: 'Ana', source: 'human', kind: 'message', text: 't', ts: 1, extra: 'no' });
  assert.deepEqual(JSON.parse(line), { type: 'message', id: 'i', from: 'Ana', origin: 'human', kind: 'message', text: 't', ts: 1 });
  assert.ok(line.endsWith('\n'));
});

test('ProcSink: one long-lived command, env, replies to the sender, title, log, self-reply dropped, clean stop', async () => {
  const cmd = `printf '{"type":"title","text":"%s"}\\n' "$LAS_CONTRACT-$LAS_AGENT-$LAS_SESSION"; echo started; `
    + `while read -r line; do echo "$line" >&2; echo '{"type":"reply","text":"pong"}'; done`;
  const { s, sent, titles, out } = sink({ command: cmd });
  let exited = false;
  s.onexit = () => { exited = true; };
  s.start();
  const pid = s.child.pid;
  await s.deliver({ envelope: { id: '1', from: 'Ana', source: 'human', kind: 'message', text: 'ping', ts: 1 } });
  await until(() => sent.length === 1);
  assert.deepEqual(sent, [['Ana', 'pong']]);
  assert.deepEqual(titles, ['1-Me-x-1']);
  await s.deliver({ envelope: { id: '2', from: 'Me', source: 'agent', kind: 'message', text: 'self', ts: 2 } });
  await until(() => out.text.includes('reply to self'));
  assert.equal(sent.length, 1, 'a reply to its own agent is never sent (it would loop back in)');
  assert.equal(s.child.pid, pid, 'the same process handles every message');
  assert.match(out.text, /started/);
  assert.match(out.text, /"text":"ping"/);
  await s.stop();
  assert.equal(exited, true, "onexit fires: the bridge ends the session");
  assert.throws(() => s.deliver({ envelope: {} }), /not running/);
});

test('ProcSink needs a command', () => {
  assert.throws(() => new ProcSink({}), TypeError);
});

test('ProcSink: the answer to a mic dictation (origin human, from the agent itself) is spoken, not sent', async () => {
  const spoken = [];
  const { s, sent, out } = sink({ command: `while read -r line; do echo '{"type":"reply","text":"hola"}'; done`, speak: async (t) => spoken.push(t) });
  s.start();
  await s.deliver({ envelope: { id: '1', from: 'Me', source: 'human', kind: 'message', text: 'dictado', ts: 1 } });
  await until(() => spoken.length === 1);
  assert.deepEqual(spoken, ['hola']);
  assert.equal(sent.length, 0);
  await s.deliver({ envelope: { id: '2', from: 'Me', source: 'agent', kind: 'message', text: 'x', ts: 2 } });
  await until(() => out.text.includes('reply to self'));
  assert.equal(spoken.length, 1, 'an agent-origin message to self is only logged');
  await s.stop();
});

test('detached ExecSink: one run per message, its output spoken for the mic, sent to another agent, never echoed into itself; housekeeping kinds skipped', async () => {
  const { ExecSink } = await import('../src/sinks/exec.js');
  const { makeAnswer } = await import('../src/answer.js');
  const sent = [], spoken = [];
  const out = { text: '', write(s) { this.text += s; } };
  const answer = makeAnswer({ agent: 'Me', send: async (to, t) => sent.push([to, t]), speak: async (t) => spoken.push(t), out });
  const sink = new ExecSink({ command: 'printf "re: "; cat', shell: '/bin/sh', echo: out, answer });
  const ctx = (from, source, kind = 'message') => ({ agent: 'Me', envelope: { id: 'i', from, source, kind, text: 'hola' }, reply: async () => assert.fail('detached never uses ctx.reply') });
  await sink.deliver(ctx('Me', 'human'));
  await sink.deliver(ctx('Ana', 'agent'));
  await sink.deliver(ctx('Me', 'agent'));
  await sink.deliver(ctx('Me', 'human', 'title-request'));
  assert.deepEqual(spoken, ['re: hola']);
  assert.deepEqual(sent, [['Ana', 're: hola']]);
  assert.match(out.text, /reply to self, not sent/);
});
