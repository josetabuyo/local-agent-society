import test from 'node:test';
import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import { StdoutSink } from '../src/sinks/stdout.js';
import { ExecSink } from '../src/sinks/exec.js';
import { ShellSink } from '../src/sinks/shell.js';
import { normalize } from '../src/envelope.js';

const ctxFor = (env, reply) => ({ envelope: normalize(env, { now: () => 0 }), agent: 'Me', reply: reply || (async () => {}) });

test('StdoutSink writes exactly one JSON line per message', async () => {
  const out = new PassThrough();
  let text = '';
  out.on('data', (c) => (text += c));
  const sink = new StdoutSink({ stream: out });
  await sink.deliver(ctxFor({ id: 'a', from: 'A', to: 'B', text: 'x' }));
  await sink.deliver(ctxFor({ id: 'b', from: 'A', to: 'B', text: 'y' }));
  const lines = text.trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(lines.map((l) => l.text), ['x', 'y']);
});

test('ExecSink runs the configured command with the text on stdin + LAS_* env and replies with its stdout', async () => {
  const replies = [];
  const echo = new PassThrough();
  echo.resume();
  const sink = new ExecSink({ command: 'printf "%s|%s|" "$LAS_FROM" "$LAS_KIND"; cat', cwd: process.cwd(), shell: '/bin/sh', echo });
  await sink.deliver(ctxFor({ from: 'Pulpo', text: 'hola', kind: 'command' }, async (t) => replies.push(t)));
  assert.deepEqual(replies, ['Pulpo|command|hola']);
  const silent = new ExecSink({ command: 'true', shell: '/bin/sh', echo });
  await silent.deliver(ctxFor({ from: 'X', text: 'ignored' }, async () => assert.fail('no output, no reply')));
  assert.throws(() => new ExecSink({}), TypeError);
});

test('ShellSink prints every message, runs only kind=command (or --all), and never runs without confirmation unless --yes', async () => {
  const out = new PassThrough();
  let printed = '';
  out.on('data', (c) => (printed += c));
  const replies = [];
  const yes = new ShellSink({ cwd: process.cwd(), shell: '/bin/sh', confirm: false, output: out });
  await yes.deliver(ctxFor({ from: 'A', text: 'echo ran-it', kind: 'message' }, async (t) => replies.push(t)));
  assert.match(printed, /A \(agent\/message\): echo ran-it/);
  assert.equal(replies.length, 0, 'plain messages are only printed');
  await yes.deliver(ctxFor({ from: 'A', text: 'echo ran-it', kind: 'command' }, async (t) => replies.push(t)));
  assert.match(printed, /ran-it\nexit 0/);
  assert.match(replies[0], /\$ echo ran-it\nran-it\n\[exit 0\]/);

  const all = new ShellSink({ shell: '/bin/sh', confirm: false, all: true, output: out });
  assert.equal(all.isRunnable(normalize({ text: 'ls' })), true);

  const input = new PassThrough();
  const asking = new ShellSink({ shell: '/bin/sh', confirm: true, all: true, input, output: out, spawnImpl: () => assert.fail('must not spawn on "n"') });
  setTimeout(() => input.write('n\n'), 5);
  await asking.deliver(ctxFor({ from: 'A', text: 'rm -rf /', kind: 'command' }));
  assert.match(printed, /skipped/);
});

test('ShellSink never runs a kind=cc copy, not even with --all', async () => {
  const { ShellSink } = await import('../src/sinks/shell.js');
  const { normalize } = await import('../src/envelope.js');
  const all = new ShellSink({ shell: '/bin/sh', confirm: false, all: true, output: new PassThrough() });
  assert.equal(all.isRunnable(normalize({ text: '[cc → shell] rm -rf x', kind: 'cc' })), false);
  assert.equal(all.isRunnable(normalize({ text: 'ls', kind: 'command' })), true);
});
