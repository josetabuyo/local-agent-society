/**
 * ExecSink — run ONE configured command per message, with the message on
 * stdin and in LAS_* env vars, and send whatever it prints back to the
 * sender. This is the "any other AI, any other tool" adapter: `--exec
 * 'codex exec -'`, `--exec 'ollama run gemma4:e4b'`, `--exec ./my-router`.
 * The bridge doesn't know or care what the command is.
 */
import { spawn } from 'node:child_process';

export class ExecSink {
  constructor({ command, cwd = process.cwd(), shell = process.env.SHELL || '/bin/sh', maxOutput = 64 * 1024, spawnImpl = spawn, echo = process.stderr }) {
    if (!command) throw new TypeError('ExecSink needs a command');
    this.name = 'exec';
    this.command = command;
    this.cwd = cwd;
    this.shell = shell;
    this.maxOutput = maxOutput;
    this.spawnImpl = spawnImpl;
    this.echo = echo;
  }

  deliver(ctx) {
    const { envelope, agent } = ctx;
    return new Promise((resolve, reject) => {
      const child = this.spawnImpl(this.shell, ['-lc', this.command], {
        cwd: this.cwd,
        env: { ...process.env, LAS_AGENT: agent, LAS_FROM: envelope.from, LAS_KIND: envelope.kind, LAS_SOURCE: envelope.source, LAS_TEXT: envelope.text, LAS_MSG_ID: envelope.id },
        stdio: ['pipe', 'pipe', 'inherit'],
      });
      let out = '';
      child.stdout.on('data', (chunk) => {
        if (out.length < this.maxOutput) out += chunk.toString('utf8');
      });
      child.on('error', reject);
      child.on('close', async (code) => {
        this.echo.write(`[las-bridge] exec for ${envelope.from} exited ${code}\n`);
        const text = out.trim();
        if (text) {
          try {
            await ctx.reply(text.slice(0, this.maxOutput));
          } catch (err) {
            this.echo.write(`[las-bridge] reply failed: ${err && err.message ? err.message : err}\n`);
          }
        }
        resolve();
      });
      child.stdin.on('error', () => {});
      child.stdin.end(envelope.text);
    });
  }
}
