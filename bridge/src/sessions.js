/**
 * Connected sessions (docs/adr/0004 phase 2) — the bridge side.
 *
 * Every running bridge is one *session* of its agent: it registers itself
 * with the backend (runtime, pid, cwd), touches its record on activity, and
 * unregisters on exit. The backend elects the DEFAULT session (last used)
 * and publishes its id, retained, on `las/agent/<name>/default-session`;
 * DefaultWatcher subscribes to that topic so the Bridge can hold the
 * agent-level mailbox while it is the default and release it the moment
 * another session becomes the default — no bridge ever talks to another,
 * and no two ever fight over the agent mailbox on purpose.
 */
import crypto from 'node:crypto';
import { EventEmitter } from 'node:events';
import mqtt from 'mqtt';
import { resolveMqttPort } from './port.js';

const REGISTRY_URL = process.env.LAS_REGISTRY_URL || 'http://localhost:8700';

export function newSessionId(runtime, { pid = process.pid, randomId = () => crypto.randomBytes(3).toString('hex') } = {}) {
  return `${runtime}-${pid}-${randomId()}`;
}

export function sessionInboxTopic(agent, sid) {
  return `las/agent/${agent}/sessions/${sid}/inbox`;
}

export function sessionMailboxClientId(agent, sid) {
  return `las-agent-${agent}-${sid}`;
}

export function defaultSessionTopic(agent) {
  return `las/agent/${agent}/default-session`;
}

/** HTTP client for the backend's session endpoints. Every call fails soft: a backend that is down must not take a bridge down. */
export class SessionRegistry {
  constructor({ agent, sid, runtime, cwd = process.cwd(), pid = process.pid, fetchImpl = globalThis.fetch, registryUrl = REGISTRY_URL, log = () => {} }) {
    Object.assign(this, { agent, sid, runtime, cwd, pid, fetchImpl, registryUrl, log });
  }

  async _call(method, path, body) {
    try {
      const res = await this.fetchImpl(`${this.registryUrl}/agents/${encodeURIComponent(this.agent)}${path}`, {
        method,
        headers: { 'content-type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      this.log(`${this.agent}: session ${method} ${path} failed (${err && err.message ? err.message : err})`);
      return null;
    }
  }

  register() {
    return this._call('POST', '/sessions', { sid: this.sid, runtime: this.runtime, pid: this.pid, cwd: this.cwd });
  }

  touch() {
    return this._call('POST', `/sessions/${encodeURIComponent(this.sid)}/touch`);
  }

  unregister() {
    return this._call('DELETE', `/sessions/${encodeURIComponent(this.sid)}`);
  }
}

/** Watches the retained default-session topic; emits 'default' with the sid (or null) on every change. */
export class DefaultWatcher extends EventEmitter {
  constructor({ agent, host = 'localhost', port, connect = mqtt.connect, log = () => {} }) {
    super();
    Object.assign(this, { agent, host, port, connect, log, client: null, current: undefined });
  }

  get topic() {
    return defaultSessionTopic(this.agent);
  }

  async start() {
    const port = await resolveMqttPort({ explicit: this.port });
    const client = this.connect(`mqtt://${this.host}:${port}`, {
      clientId: `las-default-watch-${this.agent}-${Math.random().toString(16).slice(2, 8)}`,
      clean: true,
      protocolVersion: 4,
      keepalive: 30,
      reconnectPeriod: 2000,
    });
    this.client = client;
    client.on('connect', () => client.subscribe(this.topic, { qos: 1 }));
    client.on('message', (topic, payload) => {
      if (topic !== this.topic) return;
      let sid = null;
      try {
        const data = JSON.parse(payload.toString('utf8'));
        sid = data && typeof data.sid === 'string' ? data.sid : null;
      } catch {
        sid = null;
      }
      if (sid === this.current) return;
      this.current = sid;
      this.emit('default', sid);
    });
    client.on('error', (err) => this.log(`${this.agent}: default watcher mqtt error: ${err && err.message ? err.message : err}`));
    return this;
  }

  async stop() {
    const client = this.client;
    this.client = null;
    if (!client) return;
    // A late packet on a socket we are closing is not an error worth a line.
    client.removeAllListeners('error');
    client.on('error', () => {});
    await new Promise((resolve) => client.end(true, {}, () => resolve()));
  }
}
