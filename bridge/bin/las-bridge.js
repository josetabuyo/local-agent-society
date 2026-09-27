#!/usr/bin/env node
/**
 * las-bridge <sink> [--agent NAME] [options]
 *
 * Deliver an agent's vortexia mailbox into a session runtime:
 *   claude   Claude Code channel (this process is the MCP server; start it
 *            from ~/.claude.json's mcpServers, see `las bridge install`)
 *   stdout   one JSON line per message (what `las agent listen` printed)
 *   shell    a plain terminal: print every message, offer kind="command"
 *            ones to run here (--yes to skip the prompt, --all for any text)
 *   exec     run --exec CMD per message with the text on stdin (Codex, a
 *            local model, any tool) and send its output back to the sender
 *
 * Common: --agent NAME (default: nearest .las-agent.json), --intercept-url URL
 * (first-decision hook, fails open), --port N (broker), --quiet.
 */
import { parseArgs } from 'node:util';
import {
  Bridge, MailboxSource, Pipeline, dedupInterceptor, ignoreKindsInterceptor, senderPolicyInterceptor,
  micSelfTestInterceptor, httpInterceptor, ClaudeChannelSink, StdoutSink, ShellSink, ExecSink,
  KIND, resolveAgent, StatusFile, makeSender,
} from '../src/index.js';

const { values: opts, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    agent: { type: 'string' },
    port: { type: 'string' },
    'intercept-url': { type: 'string' },
    exec: { type: 'string' },
    yes: { type: 'boolean', default: false },
    all: { type: 'boolean', default: false },
    quiet: { type: 'boolean', default: false },
    help: { type: 'boolean', default: false },
  },
});

const SINKS = ['claude', 'stdout', 'shell', 'exec'];
const sinkName = positionals[0];
if (opts.help || !SINKS.includes(sinkName)) {
  process.stderr.write(`usage: las-bridge <${SINKS.join('|')}> [--agent NAME] [--exec CMD] [--yes] [--all] [--intercept-url URL] [--port N] [--quiet]\n`);
  process.exit(opts.help ? 0 : 64);
}

// stdout is the MCP wire for the claude sink and the data stream for stdout
// — every human-facing line goes to stderr, always.
const log = opts.quiet ? () => {} : (msg) => process.stderr.write(`[las-bridge] ${msg}\n`);

let agent;
try {
  agent = resolveAgent({ name: opts.agent });
} catch (err) {
  process.stderr.write(`las-bridge: ${err.message}\n`);
  process.exit(64);
}

const send = makeSender({ from: agent.name });
const source = new MailboxSource({ agent: agent.name, port: opts.port, log });
const interceptors = [
  dedupInterceptor(),
  ignoreKindsInterceptor([KIND.MIC_SELFTEST_PONG, KIND.PROBE]),
  senderPolicyInterceptor({ log }),
  micSelfTestInterceptor({ agent: agent.name }),
];
if (opts['intercept-url']) interceptors.push(httpInterceptor({ url: opts['intercept-url'], log }));

let sink;
switch (sinkName) {
  case 'claude':
    sink = new ClaudeChannelSink({ agent: agent.name, send, log });
    break;
  case 'stdout':
    sink = new StdoutSink();
    break;
  case 'shell':
    sink = new ShellSink({ cwd: agent.dir, confirm: !opts.yes, all: opts.all });
    break;
  case 'exec':
    if (!opts.exec) {
      process.stderr.write('las-bridge exec: --exec CMD is required\n');
      process.exit(64);
    }
    sink = new ExecSink({ command: opts.exec, cwd: agent.dir });
    break;
}

const status = new StatusFile({ agent: agent.name, sink: sink.name });
const bridge = new Bridge({ agent: agent.name, source, pipeline: new Pipeline(interceptors), sink, send, status, log });

let exiting = false;
async function shutdown(code) {
  if (exiting) return;
  exiting = true;
  try {
    await bridge.stop();
  } finally {
    process.exit(code);
  }
}

source.on('connect', ({ sessionPresent, port }) => log(`${agent.name}: mailbox attached on :${port} (${sessionPresent ? 'session resumed' : 'new session'})`));
source.on('takeover', () => shutdown(2));
if (sink instanceof ClaudeChannelSink) sink.onclose = () => shutdown(0);
process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));
process.on('SIGHUP', () => shutdown(0));

bridge.run().catch((err) => {
  process.stderr.write(`las-bridge: ${err && err.stack ? err.stack : err}\n`);
  shutdown(1);
});
