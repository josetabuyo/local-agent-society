import { test } from 'node:test';
import assert from 'node:assert/strict';

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

test('ExecSink textAs=arg: the text is ONE more argument, quoted whatever it holds; stdin is empty', async () => {
  const { ExecSink, quoteArg } = await import('../src/sinks/exec.js');
  const out = { text: '', write(s) { this.text += s; } };
  const got = [];
  const probe = new ExecSink({ command: 'printf "[%s]" ', shell: '/bin/sh', echo: out, textAs: 'arg', answer: async ({ text }) => got.push(text) });
  await probe.deliver({ agent: 'Me', envelope: { id: '1', from: 'Ana', source: 'human', kind: 'message', text: "it's $HOME `x` \"q\"" } });
  assert.deepEqual(got, ["[it's $HOME `x` \"q\"]"]);
  assert.equal(quoteArg("a'b", 'linux'), "'a'\\''b'");
  assert.equal(quoteArg('a"b', 'win32'), '"a\\"b"');
});
