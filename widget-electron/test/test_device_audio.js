'use strict';

// Device audio (lib/deviceAudio.js, vortexia docs/adr/0001): a paired
// phone's dictation clips, consumed from the `las-device-audio` system
// mailbox. The file is the source of truth — deleted only after delivery,
// never on a rejection — and each clip is processed once per sha256.

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const D = require('../lib/deviceAudio');

function inbox() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'las-device-inbox-'));
  fs.mkdirSync(path.join(root, 'jose-iphone'));
  return root;
}

function clipFile(root, bytes = 'fake-m4a', target = { agent: 'Alpha' }, extra = {}) {
  const sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
  const file = path.join(root, 'jose-iphone', `${sha256}.m4a`);
  fs.writeFileSync(file, bytes);
  const notice = { type: 'device-audio', from: 'jose-iphone', label: "José's iPhone", path: file, sha256, mime: 'audio/mp4', durationMs: 3000, capturedAt: 1, target, ...extra };
  fs.writeFileSync(file.replace(/\.m4a$/, '.json'), JSON.stringify(notice));
  return { file, sha256, notice };
}

function deps(root, over = {}) {
  const calls = { delivered: [], replies: [], logs: [] };
  return {
    calls,
    roots: () => [root],
    agentExists: async (name) => name === 'Alpha',
    decode: async () => new Float32Array(16000),
    transcribe: async () => 'hola mundo',
    deliver: async (clip, text) => { calls.delivered.push({ target: clip.target, text }); return { ok: true }; },
    reply: async (to, payload) => { calls.replies.push({ to, payload }); },
    log: (level, message) => calls.logs.push(`${level} ${message}`),
    ...over,
  };
}

test('parseNotice accepts the payload, its JSON, or an envelope carrying it', () => {
  const sha256 = 'a'.repeat(64);
  const payload = { type: 'device-audio', from: 'phone', path: '/x/y.m4a', sha256, target: { agent: 'Alpha', session: 'claude' } };
  for (const input of [payload, JSON.stringify(payload), { from: 'phone', to: 'las-device-audio', text: JSON.stringify(payload) }]) {
    const res = D.parseNotice(input);
    assert.equal(res.ok, true);
    assert.deepEqual(res.clip.target, { agent: 'Alpha', session: 'claude' });
  }
});

test('parseNotice refuses a clip with no target (there is no general mic) and keeps from for the error', () => {
  const res = D.parseNotice({ type: 'device-audio', from: 'phone', path: '/x/y.m4a', sha256: 'b'.repeat(64) });
  assert.equal(res.ok, false);
  assert.match(res.error, /target/);
  assert.equal(res.from, 'phone');
  assert.equal(D.parseNotice({ type: 'other' }).ok, false);
  assert.equal(D.parseNotice({ type: 'device-audio', from: 'p', path: 'relative.m4a', sha256: 'c'.repeat(64), target: { agent: 'A' } }).ok, false);
});

test('a clip is transcribed, delivered to its target, acked to the phone and only then deleted', async () => {
  const root = inbox();
  const { file, sha256, notice } = clipFile(root, 'audio-1', { agent: 'Alpha', session: 'claude-1-aa' });
  const d = deps(root);
  const q = new D.DeviceAudioQueue(d);
  q.enqueue(D.parseNotice(notice).clip);
  await q.idle;
  assert.deepEqual(d.calls.delivered, [{ target: { agent: 'Alpha', session: 'claude-1-aa' }, text: 'hola mundo' }]);
  assert.deepEqual(d.calls.replies, [{ to: 'jose-iphone', payload: { type: 'device-audio-result', sha256, ok: true, chars: 10, text: 'hola mundo', target: { agent: 'Alpha', session: 'claude-1-aa' } } }]);
  assert.equal(fs.existsSync(file), false);
  assert.equal(fs.existsSync(file.replace(/\.m4a$/, '.json')), false, 'the sidecar goes with it');
});

test('the same sha256 twice is processed once', async () => {
  const root = inbox();
  const { notice } = clipFile(root);
  const d = deps(root);
  const q = new D.DeviceAudioQueue(d);
  assert.equal(q.enqueue(D.parseNotice(notice).clip), true);
  assert.equal(q.enqueue(D.parseNotice(notice).clip), false);
  await q.idle;
  assert.equal(d.calls.delivered.length, 1);
});

test('an unknown agent or a non-speech clip is rejected to the phone and KEPT in rejected/', async () => {
  for (const [target, transcribe, why] of [
    [{ agent: 'Nobody' }, async () => 'hola', /no agent named Nobody/],
    [{ agent: 'Alpha' }, async () => '[Música]', /music/],
  ]) {
    const root = inbox();
    const { file, sha256, notice } = clipFile(root, `x-${why}`, target);
    const d = deps(root, { transcribe });
    const q = new D.DeviceAudioQueue(d);
    q.enqueue(D.parseNotice(notice).clip);
    await q.idle;
    assert.equal(d.calls.delivered.length, 0);
    assert.equal(d.calls.replies[0].payload.ok, false);
    assert.match(d.calls.replies[0].payload.error, why);
    const rejected = path.join(path.dirname(file), 'rejected');
    assert.ok(fs.existsSync(path.join(rejected, `${sha256}.m4a`)), 'never deleted');
    assert.ok(fs.existsSync(path.join(rejected, `${sha256}.reason.txt`)));
    assert.deepEqual(D.scanInbox(root), [], 'rejected clips are not rescanned');
  }
});

test('a path outside the inbox or a sha256 mismatch is never processed', async () => {
  const root = inbox();
  const outside = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'elsewhere-')), 'secret.m4a');
  fs.writeFileSync(outside, 'secret');
  const sha = crypto.createHash('sha256').update('secret').digest('hex');
  const d = deps(root);
  const q = new D.DeviceAudioQueue(d);
  q.enqueue(D.parseNotice({ type: 'device-audio', from: 'p', path: outside, sha256: sha, target: { agent: 'Alpha' } }).clip);
  const { notice } = clipFile(root, 'real');
  q.enqueue(D.parseNotice({ ...notice, sha256: 'f'.repeat(64) }).clip);
  await q.idle;
  assert.equal(d.calls.delivered.length, 0);
  assert.deepEqual(d.calls.replies.map((r) => r.payload.error), ['path outside the device inbox', 'sha256 mismatch']);
  assert.ok(fs.existsSync(outside), 'a file outside the inbox is never touched');
});

test('a failed delivery keeps the clip on disk and lets it be retried', async () => {
  const root = inbox();
  const { file, notice } = clipFile(root);
  let attempts = 0;
  const d = deps(root, { retryDelayMs: 0, deliver: async () => (++attempts === 1 ? { ok: false, error: 'backend down' } : { ok: true }) });
  const q = new D.DeviceAudioQueue(d);
  q.enqueue(D.parseNotice(notice).clip);
  await q.idle;
  assert.ok(fs.existsSync(file), 'kept after a failed delivery');
  assert.equal(d.calls.replies.length, 0, 'the phone is not told it failed: it is still queued here');
  const [again] = D.scanInbox(root);
  assert.equal(q.enqueue(again), true, 'a retry is allowed again');
  await q.idle;
  assert.equal(fs.existsSync(file), false);
});

test('scanInbox finds clips left by a previous run, oldest first, and skips ones whose clip is gone', () => {
  const root = inbox();
  const b = clipFile(root, 'b', { agent: 'Alpha' }, { capturedAt: 20 });
  const a = clipFile(root, 'a', { agent: 'Alpha' }, { capturedAt: 10 });
  const gone = clipFile(root, 'gone');
  fs.unlinkSync(gone.file);
  assert.deepEqual(D.scanInbox(root).map((c) => c.sha256), [a.sha256, b.sha256]);
  assert.deepEqual(D.scanInbox(path.join(root, 'missing')), []);
});

test('isNonSpeechText matches Whisper non-speech tags only', () => {
  for (const t of ['[Música]', '(música)', '♪ ♪', '[BLANK_AUDIO]', '*Music*', '']) assert.equal(D.isNonSpeechText(t), true, t);
  for (const t of ['Hola, ¿me escuchás? [Música]', 'Sí.']) assert.equal(D.isNonSpeechText(t), false, t);
});

test('the renderer keeps the same non-speech rule as lib/deviceAudio.js', () => {
  const widget = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'widget.js'), 'utf8');
  const body = (src) => src.match(/function isNonSpeechText\(text\) \{[\s\S]*?\n\}/)[0];
  assert.equal(body(widget), body(fs.readFileSync(path.join(__dirname, '..', 'lib', 'deviceAudio.js'), 'utf8')));
});

test('main.js watches the inbox (no polling): a notice that never arrives does not strand a clip', () => {
  const main = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8');
  assert.match(main, /fs\.watch\(root, \{ recursive: true/);
  assert.doesNotMatch(main, /DEVICE_INBOX_RESCAN_MS/, 'no timer rescan');
  const root = inbox();
  const { notice } = clipFile(root, 'rescan');
  const q = new D.DeviceAudioQueue(deps(root));
  assert.equal(q.enqueue(D.parseNotice(notice).clip), true);
  assert.equal(q.enqueue(D.scanInbox(root)[0], { quiet: true }), false, 'the rescan finds it already queued');
});

test('a failed clip is not retried before retryDelayMs (each try re-transcribes)', async () => {
  const root = inbox();
  const { notice } = clipFile(root, 'slow-retry');
  const d = deps(root, { retryDelayMs: 60000, deliver: async () => ({ ok: false, error: 'down' }) });
  const q = new D.DeviceAudioQueue(d);
  q.enqueue(D.parseNotice(notice).clip);
  await q.idle;
  assert.equal(q.enqueue(D.scanInbox(root)[0], { quiet: true }), false, 'held back');
});

test('a failed clip retries on its own after retryDelayMs, with no scan', async () => {
  const root = inbox();
  const { file, notice } = clipFile(root, 'self-retry');
  let attempts = 0;
  const d = deps(root, { retryDelayMs: 20, deliver: async () => (++attempts === 1 ? { ok: false, error: 'down' } : { ok: true }) });
  const q = new D.DeviceAudioQueue(d);
  q.enqueue(D.parseNotice(notice).clip);
  await q.idle;
  await new Promise((r) => setTimeout(r, 60));
  await q.idle;
  assert.equal(attempts, 2);
  assert.equal(fs.existsSync(file), false);
});

function segment(root, recordingId, seg, last, extra = {}) {
  return clipFile(root, `${recordingId}-${seg}`, { agent: 'Alpha' }, { recordingId, segment: seg, last, capturedAt: seg, ...extra });
}

test('a segmented recording is delivered once, joined in segment order, when the last one is in', async () => {
  const root = inbox();
  const texts = { 0: 'uno', 1: '[Música]', 2: 'tres' };
  const files = [];
  const d = deps(root, { transcribe: async (_pcm, _agent) => texts[d._seg] });
  const q = new D.DeviceAudioQueue(d);
  for (const [seg, last] of [[2, true], [0, false], [1, false]]) {   // out of order
    const c = segment(root, 'rec-1', seg, last);
    files.push(c.file);
    d._seg = seg;
    q.enqueue(D.parseNotice(c.notice).clip);
    await q.idle;
    if (seg !== 1) assert.equal(d.calls.delivered.length, 0, 'nothing until every segment is in');
  }
  assert.deepEqual(d.calls.delivered, [{ target: { agent: 'Alpha' }, text: 'uno tres' }], 'a silent segment adds nothing');
  assert.equal(d.calls.replies.length, 3, 'a result per segment');
  assert.ok(d.calls.replies.every((r) => r.payload.ok && r.payload.recordingId === 'rec-1'));
  assert.ok(files.every((f) => !fs.existsSync(f)), 'files go only after delivery');
});

test('a recording whose last segment never comes is delivered after recordingTimeoutMs', async () => {
  const root = inbox();
  const d = deps(root, { recordingTimeoutMs: 20 });
  const q = new D.DeviceAudioQueue(d);
  const c = segment(root, 'rec-2', 0, false);
  q.enqueue(D.parseNotice(c.notice).clip);
  await q.idle;
  assert.equal(d.calls.delivered.length, 0);
  assert.ok(fs.existsSync(c.file), 'kept while waiting');
  await new Promise((r) => setTimeout(r, 60));
  await q.idle;
  assert.deepEqual(d.calls.delivered.map((x) => x.text), ['hola mundo']);
  assert.equal(fs.existsSync(c.file), false);
});

test('a failed delivery retries the whole recording together', async () => {
  const root = inbox();
  let attempts = 0;
  const d = deps(root, { retryDelayMs: 0, deliver: async (clip, text) => (++attempts === 1 ? { ok: false, error: 'down' } : (d.calls.delivered.push(text), { ok: true })) });
  const q = new D.DeviceAudioQueue(d);
  for (const [seg, last] of [[0, false], [1, true]]) {
    q.enqueue(D.parseNotice(segment(root, 'rec-3', seg, last).notice).clip);
    await q.idle;
  }
  await q.idle;
  assert.equal(attempts, 2);
  assert.deepEqual(d.calls.delivered, ['hola mundo hola mundo']);
});
