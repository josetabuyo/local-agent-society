'use strict';
/**
 * Dictations recorded on a paired phone (vortexia docs/adr/0001, "device
 * audio"): vortexia's gateway decrypts each clip into
 * <inbox>/<env>/<sha256>.m4a and publishes a notice to the SYSTEM mailbox
 * `las-device-audio` (not an agent: no LLM reads it). This module is the
 * deterministic consumer's logic, free of Electron so it can be tested:
 *
 *   parse the notice → validate (path inside the inbox, sha256 matches) →
 *   decode → transcribe → deliver to target {agent, session?} as a mic
 *   dictation → delete the clip.
 *
 * The FILE is the source of truth, not the MQTT ack (mqtt.js acks as soon
 * as the handler returns): a clip stays on disk until it was delivered, and
 * at startup the inbox is scanned so a crash mid-transcription loses
 * nothing. A clip is processed once per sha256, one at a time.
 */
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const SYSTEM_MAILBOX = 'las-device-audio';
const SHA256_RE = /^[0-9a-f]{64}$/;

/** True when the text holds no words: only non-speech tags ([Música],
 * [BLANK_AUDIO], *Music*), notes, punctuation. Mirrors isNonSpeechText in
 * renderer/widget.js (the sandboxed renderer can't require this file). */
function isNonSpeechText(text) {
  const words = String(text || '')
    .replace(/[[(（【][^\])）】]*[\])）】]/g, ' ')
    .replace(/\*[^*]*\*/g, ' ')
    .replace(/[♪♫♬*.…,;:!?¡¿\-–—'"«»\s]/g, '');
  return words.length === 0;
}

/**
 * A notice's payload → `{ ok: true, clip }` or `{ ok: false, error, from? }`.
 * Accepts the payload object itself, a JSON string of it, or a vortexia
 * envelope whose `text` is that JSON.
 */
function parseNotice(input) {
  let payload = input;
  if (payload && typeof payload === 'object' && typeof payload.text === 'string' && payload.type === undefined) payload = payload.text;
  if (typeof payload === 'string') {
    try {
      payload = JSON.parse(payload);
    } catch {
      return { ok: false, error: 'not JSON' };
    }
  }
  if (!payload || typeof payload !== 'object' || payload.type !== 'device-audio') return { ok: false, error: 'not a device-audio notice' };
  const from = typeof payload.from === 'string' && payload.from ? payload.from : null;
  const fail = (error) => ({ ok: false, error, from });
  if (!from) return fail('missing from');
  if (typeof payload.path !== 'string' || !path.isAbsolute(payload.path)) return fail('missing absolute path');
  const sha256 = String(payload.sha256 || '').toLowerCase();
  if (!SHA256_RE.test(sha256)) return fail('bad sha256');
  const target = payload.target;
  if (!target || typeof target !== 'object' || typeof target.agent !== 'string' || !target.agent.trim()) return fail('missing target.agent (there is no general mic)');
  const session = typeof target.session === 'string' && target.session.trim() ? target.session.trim() : null;
  return {
    ok: true,
    clip: {
      from,
      label: typeof payload.label === 'string' ? payload.label : from,
      path: payload.path,
      sha256,
      mime: typeof payload.mime === 'string' ? payload.mime : 'audio/mp4',
      durationMs: Number.isFinite(payload.durationMs) ? payload.durationMs : null,
      capturedAt: Number.isFinite(payload.capturedAt) ? payload.capturedAt : null,
      target: { agent: target.agent.trim(), ...(session ? { session } : {}) },
    },
  };
}

/** Is `file` (after resolving symlinks) inside one of `roots`? */
function isInsideRoots(file, roots) {
  let real;
  try {
    real = fs.realpathSync(file);
  } catch {
    return false;
  }
  return roots.some((root) => {
    let r;
    try {
      r = fs.realpathSync(root);
    } catch {
      return false;
    }
    const rel = path.relative(r, real);
    return rel && !rel.startsWith('..') && !path.isAbsolute(rel);
  });
}

function sha256OfFile(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

/**
 * Clips left in the inbox by a previous run: every `<env>/<sha256>.json`
 * sidecar (the notice, written next to the clip) whose clip still exists.
 * Returns parsed clips; unreadable sidecars are reported through `onSkip`.
 */
function scanInbox(root, onSkip = () => {}) {
  const clips = [];
  let envs;
  try {
    envs = fs.readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory());
  } catch {
    return clips;
  }
  for (const env of envs) {
    const dir = path.join(root, env.name);
    for (const name of fs.readdirSync(dir)) {
      if (!name.endsWith('.json')) continue;
      const sidecar = path.join(dir, name);
      let parsed;
      try {
        parsed = parseNotice(fs.readFileSync(sidecar, 'utf8'));
      } catch (err) {
        onSkip(sidecar, String(err));
        continue;
      }
      if (!parsed.ok) onSkip(sidecar, parsed.error);
      else if (fs.existsSync(parsed.clip.path)) clips.push(parsed.clip);
    }
  }
  return clips.sort((a, b) => (a.capturedAt || 0) - (b.capturedAt || 0));
}

/**
 * One clip at a time, once per sha256. `deps`:
 *   roots()                         → inbox directories a clip may live in
 *   agentExists(name)               → Promise<boolean>
 *   decode(buffer, mime)            → Promise<Float32Array> (mono 16 kHz)
 *   transcribe(pcm, agent)          → Promise<string>
 *   deliver(clip, text)             → Promise<{ok, error?}>
 *   reply(to, payload)              → Promise<void>   (error/ack to the device)
 *   log(level, message)
 */
class DeviceAudioQueue {
  constructor(deps) {
    this.deps = deps;
    this.pending = [];
    this.seen = new Set();   // sha256 queued or done this run
    this.running = false;
    this.idle = Promise.resolve();
  }

  /** → true when queued; false when this sha256 is already queued or done
   * (`quiet` skips the debug line, for the periodic rescan). */
  enqueue(clip, { quiet = false } = {}) {
    if (this.seen.has(clip.sha256)) {
      if (!quiet) this.deps.log('debug', `device-audio: ${clip.sha256.slice(0, 12)} already queued — skipped`);
      return false;
    }
    this.seen.add(clip.sha256);
    this.pending.push(clip);
    if (!this.running) this.idle = this._drain();
    return true;
  }

  async _drain() {
    this.running = true;
    try {
      while (this.pending.length) {
        const clip = this.pending.shift();
        try {
          await this._process(clip);
        } catch (err) {
          // Not delivered: the clip stays on disk for the next run's scan.
          // Retried by a later scan, but not sooner than retryDelayMs: the
          // inbox is rescanned every few seconds and each try re-transcribes.
          const delay = this.deps.retryDelayMs ?? 60000;
          this.deps.log('error', `device-audio: ${clip.sha256.slice(0, 12)} failed, kept for retry in ${Math.round(delay / 1000)}s: ${err && err.stack ? err.stack : err}`);
          if (delay <= 0) this.seen.delete(clip.sha256);
          else setTimeout(() => this.seen.delete(clip.sha256), delay).unref?.();
        }
      }
    } finally {
      this.running = false;
    }
  }

  async _process(clip) {
    const { deps } = this;
    const short = clip.sha256.slice(0, 12);
    // A rejected clip is never deleted — a dictation may be impossible to
    // repeat: it moves to <inbox>/<env>/rejected/ and the device is told why.
    const fail = async (error, { keep = true } = {}) => {
      deps.log('warn', `device-audio: ${short} from ${clip.from} rejected: ${error}`);
      await deps.reply(clip.from, { type: 'device-audio-result', sha256: clip.sha256, ok: false, error, target: clip.target });
      if (keep) rejectClip(clip, error, deps);
    };
    if (!isInsideRoots(clip.path, deps.roots())) return fail('path outside the device inbox', { keep: false });
    if (!fs.existsSync(clip.path)) return deps.log('info', `device-audio: ${short} no longer on disk — already handled`);
    if (sha256OfFile(clip.path) !== clip.sha256) return fail('sha256 mismatch'); 
    if (!(await deps.agentExists(clip.target.agent))) return fail(`no agent named ${clip.target.agent}`);

    deps.log('info', `device-audio: ${short} from ${clip.label} → ${clip.target.agent}${clip.target.session ? `/${clip.target.session}` : ''} (${clip.durationMs != null ? `${(clip.durationMs / 1000).toFixed(1)}s` : '?s'})`);
    const pcm = await deps.decode(fs.readFileSync(clip.path), clip.mime);
    const text = (await deps.transcribe(pcm, clip.target.agent)).trim();
    if (!text || isNonSpeechText(text)) return fail(text ? 'only music/noise, no speech' : 'nothing heard');
    const res = await deps.deliver(clip, text);
    if (!res || !res.ok) throw new Error(`delivery failed: ${res && res.error}`);
    await deps.reply(clip.from, { type: 'device-audio-result', sha256: clip.sha256, ok: true, chars: text.length, target: clip.target });
    removeClip(clip, deps);
  }
}

function sidecarOf(file) {
  return file.replace(/\.[^./]+$/, '.json');
}

/** Move the clip (+ sidecar, + why) into rejected/ beside it; never deletes. */
function rejectClip(clip, reason, deps) {
  const dir = path.join(path.dirname(clip.path), 'rejected');
  try {
    fs.mkdirSync(dir, { recursive: true });
    for (const file of [clip.path, sidecarOf(clip.path)]) {
      if (fs.existsSync(file)) fs.renameSync(file, path.join(dir, path.basename(file)));
    }
    fs.writeFileSync(path.join(dir, `${clip.sha256}.reason.txt`), `${new Date().toISOString()} ${reason}\n`);
  } catch (err) {
    deps.log('warn', `device-audio: could not move ${clip.path} to rejected/: ${err.message}`);
  }
}

/** Delete the clip and its sidecar — only ever after delivery or a final rejection. */
function removeClip(clip, deps) {
  for (const file of [clip.path, sidecarOf(clip.path)]) {
    try {
      fs.unlinkSync(file);
    } catch (err) {
      if (err.code !== 'ENOENT') deps.log('warn', `device-audio: could not delete ${file}: ${err.message}`);
    }
  }
}

module.exports = { SYSTEM_MAILBOX, isNonSpeechText, parseNotice, isInsideRoots, sha256OfFile, scanInbox, DeviceAudioQueue };
