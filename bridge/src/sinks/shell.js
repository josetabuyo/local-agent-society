/**
 * ShellSink — a terminal with NO AI in it. Every message is printed; a
 * message whose `kind` is "command" (or any message, with `--all`) is
 * offered to run in the agent's directory with the user's shell. Nothing
 * runs without a `y` on the TTY unless `--yes` was given — a mailbox can
 * hold text from anyone, and "run this" must stay a human decision until
 * a policy in front of this sink says otherwise. Output is echoed here and
 * sent back to the sender, so the agent that asked sees the result.
 */
import { spawn } from 'node:child_process';
import readline from 'node:readline';
import { KIND } from '../envelope.js';

export class ShellSink {
  constructor({
    cwd = process.cwd(),
    shell = process.env.SHELL || '/bin/sh',
    confirm = true,
    all = false,
    maxOutput = 64 * 1024,
    input = process.stdin,
    output = process.stdout,
    spawnImpl = spawn,
  } = {}) {
    this.name = 'shell';
    this.cwd = cwd;
    this.shell = shell;
    this.confirm = confirm;
    this.all = all;
    this.maxOutput = maxOutput;
    this.input = input;
    this.output = output;
    this.spawnImpl = spawnImpl;
  }

  isRunnable(envelope) {
    if (envelope.kind === KIND.CC) return false; // a for-the-record copy, even with --all
    return this.all || envelope.kind === KIND.COMMAND;
  }

  async ask(question) {
    const rl = readline.createInterface({ input: this.input, output: this.output });
    try {
      const answer = await new Promise((resolve) => rl.question(question, resolve));
      return /^y(es)?$/i.test(answer.trim());
    } finally {
      rl.close();
    }
  }

  async deliver(ctx) {
    const { envelope } = ctx;
    const stamp = new Date(envelope.ts).toISOString().slice(11, 19);
    this.output.write(`[${stamp}] ${envelope.from} (${envelope.source}/${envelope.kind}): ${envelope.text}\n`);
    if (!this.isRunnable(envelope)) return;
    if (this.confirm && !(await this.ask(`run in ${this.cwd}? [y/N] `))) {
      this.output.write('skipped\n');
      return;
    }
    const result = await this.run(envelope.text);
    this.output.write(`exit ${result.code}\n`);
    try {
      await ctx.reply(`$ ${envelope.text}\n${result.output}`.trim() + `\n[exit ${result.code}]`);
    } catch (err) {
      this.output.write(`reply failed: ${err && err.message ? err.message : err}\n`);
    }
  }

  run(command) {
    return new Promise((resolve, reject) => {
      const child = this.spawnImpl(this.shell, ['-lc', command], { cwd: this.cwd, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] });
      let output = '';
      const collect = (chunk) => {
        const s = chunk.toString('utf8');
        this.output.write(s);
        if (output.length < this.maxOutput) output += s;
      };
      child.stdout.on('data', collect);
      child.stderr.on('data', collect);
      child.on('error', reject);
      child.on('close', (code) => resolve({ code, output: output.slice(0, this.maxOutput) }));
    });
  }
}
