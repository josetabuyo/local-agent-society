/**
 * StdoutSink — one JSON line per message on stdout. What `las agent listen`
 * always printed; for scripts, a plain terminal, or any consumer that reads
 * lines (a Codex wrapper, a `jq` pipeline, a log).
 */
export class StdoutSink {
  constructor({ stream = process.stdout } = {}) {
    this.name = 'stdout';
    this.stream = stream;
  }

  deliver(ctx) {
    return new Promise((resolve, reject) => {
      this.stream.write(JSON.stringify(ctx.envelope) + '\n', (err) => (err ? reject(err) : resolve()));
    });
  }
}
