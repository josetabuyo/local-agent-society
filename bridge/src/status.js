/**
 * One small JSON file per running bridge, so anything outside this process
 * (the /las-agent skill via `las bridge status`, the widget one day) can ask
 * "is this agent's mailbox being delivered right now, and to what?" without
 * opening an MQTT connection. Lives in the repo's gitignored session/ dir —
 * runtime state, like widget.log.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function defaultSessionDir() {
  return process.env.LAS_SESSION_DIR || path.resolve(__dirname, '..', '..', 'session');
}

export function statusPath(agent, dir = defaultSessionDir()) {
  return path.join(dir, `bridge-${agent}.json`);
}

export class StatusFile {
  constructor({ agent, sink, dir = defaultSessionDir(), pid = process.pid, now = Date.now }) {
    this.file = statusPath(agent, dir);
    this.now = now;
    this.state = { agent, sink, pid, armed: false, delivered: 0, lastDeliveredAt: null, startedAt: now(), updatedAt: now() };
  }

  update(patch) {
    Object.assign(this.state, patch, { updatedAt: this.now() });
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      fs.writeFileSync(this.file, JSON.stringify(this.state, null, 2));
    } catch {
      // status is advisory — never let it take the bridge down
    }
    return this.state;
  }

  bump() {
    return this.update({ delivered: this.state.delivered + 1, lastDeliveredAt: this.now() });
  }

  remove() {
    try {
      fs.unlinkSync(this.file);
    } catch {
      // already gone
    }
  }
}

/** Read another process's status file; null when absent or unreadable. */
export function readStatus(agent, dir = defaultSessionDir()) {
  try {
    return JSON.parse(fs.readFileSync(statusPath(agent, dir), 'utf8'));
  } catch {
    return null;
  }
}
