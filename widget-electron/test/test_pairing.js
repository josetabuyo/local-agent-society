'use strict';

// Pairing a phone (lib/pairing.js, vortexia docs/adr/0001 §10): request /
// result by id over the local broker, the retained friends and pending
// lists, and the Phones window wired into main.js.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const P = require('../lib/pairing');

function control(over = {}) {
  const sent = [];
  const seen = { changes: 0, events: [], newPending: [] };
  const c = new P.PairingControl({
    publish: (topic, payload) => sent.push({ topic, payload: JSON.parse(payload) }),
    onChange: () => { seen.changes += 1; },
    onEvent: (e) => seen.events.push(e),
    onNewPending: (p) => seen.newPending.push(p.sessionId),
    timeoutMs: 50,
    ...over,
  });
  c.setConnected(true);
  return { c, sent, seen };
}

test('a request goes to vortexia/control/<what>/<verb> and resolves on the matching result id', async () => {
  const { c, sent } = control();
  const pending = c.start("José's iPhone");
  assert.equal(sent[0].topic, 'vortexia/control/pair/start');
  assert.equal(sent[0].payload.role, 'device');
  assert.equal(sent[0].payload.label, "José's iPhone");
  c.handle('vortexia/control/pair/start/result', { id: 'someone-else', ok: false });
  c.handle('vortexia/control/pair/start/result', { id: sent[0].payload.id, ok: true, sessionId: 's1', uri: 'vxpair:1?x', expiresAt: 9 });
  assert.deepEqual(await pending, { ok: true, sessionId: 's1', uri: 'vxpair:1?x', expiresAt: 9 });
  c.revoke('uy-mac');
  c.decide('s1', 1);
  assert.deepEqual(sent.slice(1).map((s) => [s.topic, s.payload.envName || s.payload.accept]), [
    ['vortexia/control/friends/revoke', 'uy-mac'],
    ['vortexia/control/pair/decide', true],
  ]);
});

test('no answer, or no connection, resolves {ok:false} — it never throws or hangs', async () => {
  const { c } = control();
  assert.match((await c.cancel('s1')).error, /did not answer/);
  const inflight = c.revoke('x');
  c.setConnected(false);
  assert.match((await inflight).error, /disconnected/);
  assert.match((await c.start()).error, /not connected/);
});

test('friends: revoked ones are hidden, phones come first', () => {
  const { c } = control();
  c.handle(P.FRIENDS_TOPIC, { friends: [
    { envName: 'uy-mac', role: 'env', label: 'uy-mac', revokedAt: null },
    { envName: 'old-phone', role: 'device', label: 'Old', revokedAt: 5 },
    { envName: 'jose-iphone', role: 'device', label: "José's iPhone", lastSeen: 7 },
  ] });
  assert.deepEqual(c.state().friends.map((f) => [f.envName, f.role]), [['jose-iphone', 'device'], ['uy-mac', 'env']]);
  assert.equal(c.state().friends[0].lastSeen, 7);
});

test('a pending request is announced once, and an expired one is not shown', () => {
  let now = 1000;
  const { c, seen } = control({ now: () => now });
  const req = { sessionId: 's1', role: 'device', envName: 'jose-iphone', label: 'iPhone', fingerprint: '3F9A·C21E·77B0·4D18', expiresAt: 2000 };
  c.handle(P.PENDING_TOPIC, { pending: [req] });
  c.handle(P.PENDING_TOPIC, { pending: [req] });
  assert.deepEqual(seen.newPending, ['s1']);
  assert.equal(c.state().pending.length, 1);
  now = 3000;
  assert.equal(c.state().pending.length, 0);
  c.handle(P.EVENTS_TOPIC, { type: 'paired', sessionId: 's1', envName: 'jose-iphone' });
  assert.deepEqual(seen.events, [{ type: 'paired', sessionId: 's1', envName: 'jose-iphone' }]);
});

test('main.js routes the pairing topics before device-audio and ships the Phones window', () => {
  const root = path.join(__dirname, '..');
  const main = fs.readFileSync(path.join(root, 'main.js'), 'utf8');
  assert.match(main, /if \(pairing\.TOPICS\.includes\(topic\)\) return pairingControl\.handle\(topic, envelope\);/);
  assert.match(main, /subscribe\(pairing\.TOPICS/);
  // Closing the window burns a QR still on screen.
  assert.match(main, /pairingWindow\.on\('closed'[\s\S]{0,300}pairingControl\.cancel\(/);
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  assert.ok(pkg.build.files.includes('pairing-preload.js'));
  assert.ok(pkg.dependencies.qrcode);
  for (const f of ['renderer/pairing.html', 'renderer/pairing.js', 'pairing-preload.js']) assert.ok(fs.existsSync(path.join(root, f)), f);
  assert.match(fs.readFileSync(path.join(root, 'renderer', 'index.html'), 'utf8'), /id="pairingOpen"/);
});

test('the QR carries a trimmed URI: no relays, at most two LAN addresses, IPs first', () => {
  const full = 'vxpair:1?env=ba-mac&pk=ab12&t=tok_-x&lan=ba-mac.local:9014,192.168.0.16:9014,10.0.0.2:9014&ts=100.1.2.3:9014&r=wss://relay.damus.io,wss://nos.lol';
  const q = new URLSearchParams(P.qrUri(full).split('?')[1]);
  assert.equal(q.get('r'), null);
  assert.equal(q.get('lan'), '192.168.0.16:9014,10.0.0.2:9014');
  assert.deepEqual([q.get('env'), q.get('pk'), q.get('t'), q.get('ts')], ['ba-mac', 'ab12', 'tok_-x', '100.1.2.3:9014']);
  assert.ok(P.qrUri(full).length < full.length);
  assert.equal(P.qrUri('not a uri'), 'not a uri');
});
