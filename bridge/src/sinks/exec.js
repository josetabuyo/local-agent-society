/**
 * ExecSink — run ONE configured command per message, with the message on
 * stdin and in LAS_* env vars, and send whatever it prints back to the
 * sender. This is the "any other AI, any other tool" adapter: `--exec
 * 'codex exec --yolo -'`, `--exec 'ollama run gemma4:e4b'`, `--exec ./my-router`.
 * The bridge doesn't know or care what the command is.
 */
import { spawn } from 'node:child_process';

/** One argument for `sh -lc` (POSIX) or `cmd /c` (Windows), however odd the text. */
export function quoteArg(text, platform = process.platform) {
  const t = String(text);
  if (platform === 'win32') return `"${t.replace(/(\\*)"/g, '$1$1\\"').replace(/(\\+)$/, '$1$1').replace(/%/g, '"%"')}"`;
  return `'${t.replace(/'/g, `'\\''`)}'`;
}

export class ExecSink {
  constructor({ command, cwd = process.cwd(), shell = process.env.SHELL || '/bin/sh', maxOutput = 64 * 1024, spawnImpl = spawn, echo = process.stderr, answer = null, textAs = 'stdin' }) {
    if (!command) throw new TypeError('ExecSink needs a command');
    this.name = 'exec';
    this.command = command;
    this.cwd = cwd;
    this.shell = shell;
    this.maxOutput = maxOutput;
    this.spawnImpl = spawnImpl;
    this.echo = echo;
    // A detached session (ADR 0006) routes its answers through answer.js
    // (spoken for the mic, never echoed into itself); otherwise: reply to the sender.
    this.answer = answer;
    // 'stdin' (the default): the text is the command's input. 'arg' (`las <command…>`):
    // it is appended as ONE more argument — `echo Recibido: 'what the mic heard'`.
    this.textAs = textAs;
  }

  deliver(ctx) {
    const { envelope, agent } = ctx;
    // Detached, the command is a one-shot request runner: housekeeping kinds
    // (a title request…) are not requests for it.
    if (this.answer && !['message', 'command'].includes(envelope.kind)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const isWin = process.platform === 'win32';
      const line = this.textAs === 'arg' ? `${this.command} ${quoteArg(envelope.text)}` : this.command;
      const [file, args] = isWin ? [process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', line]] : [this.shell, ['-lc', line]];
      const child = this.spawnImpl(file, args, {
        cwd: this.cwd,
        env: { ...process.env, LAS_AGENT: agent, LAS_AGENT_DIR: this.cwd, LAS_FROM: envelope.from, LAS_KIND: envelope.kind, LAS_SOURCE: envelope.source, LAS_TEXT: envelope.text, LAS_MSG_ID: envelope.id },
        stdio: ['pipe', 'pipe', 'inherit'],
      });
      let out = '';
      child.stdout.on('data', (chunk) => {
        const s = chunk.toString('utf8');
        this.echo.write(s); // the human at this terminal sees the answer too
        if (out.length < this.maxOutput) out += s;
      });
      child.on('error', reject);
      child.on('close', async (code) => {
        this.echo.write(`[las-bridge] exec for ${envelope.from} exited ${code}\n`);
        const text = out.trim();
        if (text) {
          try {
            const reply = text.slice(0, this.maxOutput);
            if (this.answer) await this.answer({ to: envelope.from, text: reply, origin: envelope.source });
            else await ctx.reply(reply);
          } catch (err) {
            this.echo.write(`[las-bridge] reply failed: ${err && err.message ? err.message : err}\n`);
          }
        }
        resolve();
      });
      child.stdin.on('error', () => {});
      child.stdin.end(this.textAs === 'arg' ? '' : envelope.text);
    });
  }
}
