'use strict';
/**
 * Pairing a phone with this Mac, over vortexia's local control topics
 * (vortexia docs/adr/0001 §10). Electron-free so it can be tested: it only
 * needs something that publishes and a feed of (topic, json) messages.
 *
 *   request: vortexia/control/<what>/<verb> {id, …} → …/result {id, ok, …}
 *   state:   vortex-relay/friends (retained), vortexia/pair/pending (retained)
 *   events:  vortexia/pair/events {type: paired|rejected|expired|cancelled, sessionId, envName?}
 *
 * The friends list holds no keys — only envName/role/label/lastSeen.
 */
const crypto = require('crypto');

const FRIENDS_TOPIC = 'vortex-relay/friends';
const PENDING_TOPIC = 'vortexia/pair/pending';
const EVENTS_TOPIC = 'vortexia/pair/events';
const CONTROL_RESULT_TOPICS = [
  'vortexia/control/pair/start/result',
  'vortexia/control/pair/cancel/result',
  'vortexia/control/pair/decide/result',
  'vortexia/control/friends/revoke/result',
  'vortexia/control/friends/rename/result',
];
const TOPICS = [FRIENDS_TOPIC, PENDING_TOPIC, EVENTS_TOPIC, ...CONTROL_RESULT_TOPICS];
const REQUEST_TIMEOUT_MS = 8000;

/** Friends that are still friends, phones first, then by label. */
function activeFriends(payload) {
  const list = payload && Array.isArray(payload.friends) ? payload.friends : [];
  return list
    .filter((f) => f && typeof f.envName === 'string' && !f.revokedAt)
    .map((f) => ({
      envName: f.envName,
      role: f.role === 'device' ? 'device' : 'env',
      label: typeof f.label === 'string' && f.label ? f.label : f.envName,
      addedAt: Number.isFinite(f.addedAt) ? f.addedAt : null,
      lastSeen: Number.isFinite(f.lastSeen) ? f.lastSeen : null,
    }))
    .sort((a, b) => (a.role === b.role ? a.label.localeCompare(b.label) : a.role === 'device' ? -1 : 1));
}

/** Pending requests not yet past their expiry. */
function livePending(payload, now = Date.now()) {
  const list = payload && Array.isArray(payload.pending) ? payload.pending : [];
  return list.filter((p) => p && typeof p.sessionId === 'string' && (!Number.isFinite(p.expiresAt) || p.expiresAt > now));
}

/**
 * `publish(topic, payloadString)` sends; feed every message on TOPICS to
 * `handle(topic, json)`. `onChange(state)` fires on any state change;
 * `onEvent(event)` on each outcome event; `onNewPending(request)` once per
 * sessionId that newly needs a decision.
 */
class PairingControl {
  constructor({ publish, onChange = () => {}, onEvent = () => {}, onNewPending = () => {}, now = Date.now, timeoutMs = REQUEST_TIMEOUT_MS }) {
    this.publish = publish;
    this.onChange = onChange;
    this.onEvent = onEvent;
    this.onNewPending = onNewPending;
    this.now = now;
    this.timeoutMs = timeoutMs;
    this.friends = [];
    this.pending = [];
    this.connected = false;
    this.waiting = new Map();      // id → {resolve, timer}
    this.announced = new Set();    // pending sessionIds already surfaced
  }

  state() {
    return { connected: this.connected, friends: this.friends, pending: livePending({ pending: this.pending }, this.now()) };
  }

  setConnected(connected) {
    if (this.connected === connected) return;
    this.connected = connected;
    if (!connected) {
      for (const [id, w] of this.waiting) {
        clearTimeout(w.timer);
        w.resolve({ ok: false, error: 'vortexia disconnected' });
        this.waiting.delete(id);
      }
    }
    this.onChange(this.state());
  }

  handle(topic, msg) {
    if (topic === FRIENDS_TOPIC) {
      this.friends = activeFriends(msg);
      this.onChange(this.state());
    } else if (topic === PENDING_TOPIC) {
      this.pending = msg && Array.isArray(msg.pending) ? msg.pending : [];
      for (const p of livePending(msg, this.now())) {
        if (this.announced.has(p.sessionId)) continue;
        this.announced.add(p.sessionId);
        this.onNewPending(p);
      }
      this.onChange(this.state());
    } else if (topic === EVENTS_TOPIC) {
      if (msg && typeof msg.type === 'string') this.onEvent(msg);
    } else if (CONTROL_RESULT_TOPICS.includes(topic)) {
      const w = msg && this.waiting.get(msg.id);
      if (!w) return;
      clearTimeout(w.timer);
      this.waiting.delete(msg.id);
      const { id: _id, ts: _ts, ...rest } = msg;
      w.resolve(rest);
    }
  }

  /** → Promise<{ok, …}>; never rejects (an error is {ok:false, error}). */
  request(what, verb, body = {}) {
    if (!this.connected) return Promise.resolve({ ok: false, error: 'vortexia is not connected' });
    const id = crypto.randomUUID();
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.waiting.delete(id);
        resolve({ ok: false, error: `vortexia did not answer ${what}/${verb}` });
      }, this.timeoutMs);
      this.waiting.set(id, { resolve, timer });
      try {
        this.publish(`vortexia/control/${what}/${verb}`, JSON.stringify({ ...body, id }));
      } catch (err) {
        clearTimeout(timer);
        this.waiting.delete(id);
        resolve({ ok: false, error: String(err && err.message ? err.message : err) });
      }
    });
  }

  start(label) {
    return this.request('pair', 'start', { role: 'device', ...(label ? { label } : {}) });
  }
  cancel(sessionId) {
    return this.request('pair', 'cancel', { sessionId });
  }
  decide(sessionId, accept) {
    return this.request('pair', 'decide', { sessionId, accept: !!accept });
  }
  revoke(envName) {
    return this.request('friends', 'revoke', { envName });
  }
  rename(envName, label) {
    return this.request('friends', 'rename', { envName, label });
  }
}

module.exports = { TOPICS, FRIENDS_TOPIC, PENDING_TOPIC, EVENTS_TOPIC, activeFriends, livePending, PairingControl };
