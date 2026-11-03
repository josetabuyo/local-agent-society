/**
 * ProcSink — a DETACHED session (docs/adr/0006): ONE long-lived command,
 * started once, fed every mailbox message as a JSON line on stdin. What it
 * prints as protocol JSON on stdout becomes replies / the session title;
 * everything else (and all of stderr) goes to the log, which is this
 * bridge's own stderr — `las detach` points that at the session's log file.
 *
 * LAS takes no responsibility for what thinks inside the command: Pulpo,
 * a script, anything that honours the contract.
 */
import { spawn } from 'node:child_process';
import readline from 'node:readline';

export const PROC_CONTRACT = '1';
const KILL_AFTER_MS = 5000;

/** One protocol line from the command's stdout, or null when it is just log text. */
export function parseProcLine(line) {
  const s = line.trim();
  if (!s.startsWith('{')) return null;
  let obj;
  try {
    obj = JSON.parse(s);
  } catch {
    return null;
  }
  if (!obj || typeof obj.text !== 'string') return null;
  if (obj.type === 'reply') return { type: 'reply', text: obj.text, to: typeof obj.to === 'string' && obj.to ? obj.to : null };
  if (obj.type === 'title') return { type: 'title', text: obj.text };
  return null;
}

/** The stdin line for one envelope — only the fields the contract promises. */
export function procMessageLine(envelope) {
  return JSON.stringify({
    type: 'message', id: envelope.id, from: envelope.from, origin: envelope.source,
    kind: envelope.kind, text: envelope.text, ts: envelope.ts,
  }) + '\n';
}

export class ProcSink {
  constructor({ command, agent, sid, cwd = process.cwd(), env = {}, send, setTitle = async () => {}, shell = process.env.SHELL || '/bin/sh',
    spawnImpl = spawn, log = (msg) => process.stderr.write(`[las-bridge] ${msg}\n`), out = process.stderr, killAfterMs = KILL_AFTER_MS }) {
    if (!command) throw new TypeError('ProcSink needs a command');
    Object.assign(this, { command, agent, sid, cwd, env, send, setTitle, shell, spawnImpl, log, out, killAfterMs });
    this.name = 'proc';
    this.child = null;
    this.lastFrom = null;
    this.onexit = null;
  }

  start() {
    const isWin = process.platform === 'win32';
    const [file, args] = isWin ? [process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', this.command]] : [this.shell, ['-lc', this.command]];
    this.child = this.spawnImpl(file, args, {
      cwd: this.cwd,
      env: { ...process.env, ...this.env, LAS_CONTRACT: PROC_CONTRACT, LAS_AGENT: this.agent, LAS_AGENT_DIR: this.cwd, LAS_SESSION: this.sid },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.log(`${this.agent}: started \`${this.command}\` pid ${this.child.pid}`);
    this.child.stdin.on('error', () => {});
    readline.createInterface({ input: this.child.stdout }).on('line', (line) => this._onLine(line));
    this.child.stderr.on('data', (chunk) => this.out.write(chunk));
    this.child.on('error', (err) => this.log(`${this.agent}: command failed to start (${err.message})`));
    this.child.on('close', (code, signal) => {
      this.log(`${this.agent}: command exited ${signal || code}`);
      this.child = null;
      if (this.onexit) this.onexit(code);
    });
    return this;
  }

  async _onLine(line) {
    const msg = parseProcLine(line);
    if (!msg) {
      this.out.write(line + '\n');
      return;
    }
    try {
      if (msg.type === 'title') await this.setTitle(msg.text);
      else {
        const to = msg.to || this.lastFrom;
        if (!to) throw new Error('reply with no "to" and no message handled yet');
        // Its own agent's mailbox may be this very session: a reply there comes
        // straight back in, and an echoing command loops forever. Log it instead.
        if (to === this.agent) {
          this.out.write(`[reply to self, not sent] ${msg.text}\n`);
          return;
        }
        await this.send(to, msg.text);
      }
    } catch (err) {
      this.log(`${this.agent}: ${msg.type} failed (${err && err.message ? err.message : err})`);
    }
  }

  deliver(ctx) {
    if (!this.child) throw new Error('command is not running');
    this.lastFrom = ctx.envelope.from;
    return new Promise((resolve, reject) => {
      this.child.stdin.write(procMessageLine(ctx.envelope), (err) => (err ? reject(err) : resolve()));
    });
  }

  /** Close stdin (the polite "we're done"), SIGTERM, then kill after a grace period. */
  stop() {
    const child = this.child;
    if (!child) return Promise.resolve();
    return new Promise((resolve) => {
      const timer = setTimeout(() => child.kill('SIGKILL'), this.killAfterMs);
      child.once('close', () => {
        clearTimeout(timer);
        resolve();
      });
      child.stdin.end();
      child.kill('SIGTERM');
    });
  }
}
