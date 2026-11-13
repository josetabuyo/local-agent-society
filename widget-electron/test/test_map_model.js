'use strict';

// The map's element-type registry (renderer/map-model.js, docs/adr/0007):
// every item gets one type, counts per type, hidden types filtered out,
// sections for the Canvas/List views. The map window only draws this.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Map_ = require('../renderer/map-model.js');

const ROOT = path.resolve(__dirname, '..');
const read = (...p) => fs.readFileSync(path.join(ROOT, ...p), 'utf8');

const world = {
  agentName: 'Me',
  colorOf: (n) => ({ Me: '#112233', Vortexia: '#f0e0a0' })[n],
  sessions: [
    { sid: 'claude-1-a', runtime: 'claude', title: 'Map window' },
    { sid: 'claudeRelay-2-b', runtime: 'claudeRelay' },
    { sid: 'codex-3-c', runtime: 'codex' },
    { sid: 'shell-4-d', runtime: 'shell', intelligent: false },
    { sid: 'pulpo-5-e', runtime: 'pulpo', detached: { command: 'pulpo las', log: '/x.log' } },
  ],
  friends: [{ name: 'Vortexia', registered: true, sessions: 1 }],
  elements: [
    { id: 'repo:.', type: 'repo', path: '.', abs_path: '/d/me', label: 'me', exists: true, github: 'acme/me', branch: 'main' },
    { id: 'repo:gone', type: 'repo', path: 'gone', label: 'gone', exists: false, github: null },
    { id: 'url:https://x.y/a', type: 'url', url: 'https://x.y/a', label: 'A' },
  ],
};

test('buildMapItems: one type per item — a type per runtime, commands, friends, repos, urls', () => {
  const items = Map_.buildMapItems(world);
  assert.deepEqual(items.map((i) => i.type), ['claude', 'claudeRelay', 'codex', 'shell', 'command', 'friend', 'repo', 'repo', 'url']);
  const [repo, gone, url] = items.slice(-3);
  assert.equal(repo.detail, 'acme/me · main');
  assert.equal(repo.href, 'https://github.com/acme/me');
  assert.equal(repo.color, '#112233', 'elements wear the owning agent color');
  assert.match(gone.detail, /missing/);
  assert.equal(gone.href, null);
  assert.equal(url.detail, 'x.y');
  assert.equal(url.href, 'https://x.y/a');
  assert.equal(items[5].color, '#f0e0a0', 'a friend keeps its own color');
});

test('an unknown runtime still lands on a type (Other terminals), never undefined', () => {
  const [item] = Map_.buildMapItems({ agentName: 'Me', sessions: [{ sid: 'x-1-z', runtime: 'gemini' }] });
  assert.equal(item.type, 'terminal');
});

test('countByType lists every registered type, zero included; visible() drops hidden types', () => {
  const items = Map_.buildMapItems(world);
  const counts = Map_.countByType(items);
  assert.deepEqual(Object.keys(counts), Map_.TYPES.map((t) => t.id));
  assert.equal(counts.repo, 2);
  assert.equal(counts.terminal, 0);
  assert.deepEqual(Map_.visible(items, ['repo', 'claude']).map((i) => i.type), ['claudeRelay', 'codex', 'shell', 'command', 'friend', 'url']);
});

test('sections: by type in registry order, empty ones only on request, hidden types never', () => {
  const items = Map_.buildMapItems(world);
  assert.deepEqual(Map_.sections(items, { by: 'type' }).map((s) => s.id), ['claude', 'claudeRelay', 'codex', 'shell', 'command', 'friend', 'repo', 'url']);
  assert.ok(Map_.sections(items, { by: 'type', showEmpty: true }).some((s) => s.id === 'terminal'));
  assert.ok(!Map_.sections(items, { by: 'type', showEmpty: true, hidden: ['terminal'] }).some((s) => s.id === 'terminal'));
  assert.deepEqual(Map_.sections(items, { by: 'group' }).map((s) => s.id), ['sessions', 'agents', 'tools', 'links']);
  const [all] = Map_.sections(items, { by: 'none' });
  assert.equal(all.items.length, items.length);
});

test('the map window: one board (no Display popover), the panel tiles with their whole button bar, plus a ✕', () => {
  const html = read('renderer', 'map.html');
  assert.ok(html.indexOf('society-model.js') < html.indexOf('map-model.js'), 'society-model first: map-model builds on it');
  assert.ok(html.includes('id="layoutSeg"'), 'Canvas/List inside the board, top right');
  for (const gone of ['displayBtn', 'groupSeg', 'typeChips', 'showEmpty', 'id="summary"']) assert.ok(!html.includes(gone), `${gone} was removed (José, 2026-11-10)`);
  const js = read('renderer', 'map.js');
  assert.match(js, /V\.renderPanel\(box, items, positions, handlers, \{ empty \}\)/, 'the same tiles as the panel, not a read-only copy');
  assert.match(js, /V\.listRow\(item, handlers\)/, 'the List layout is the panel list row');
  for (const action of ['mic', 'keyboard', 'settings', 'speaker', 'find', 'log', 'unlink', 'open', 'exit']) {
    assert.match(js, new RegExp(`action === '${action}'`), `the map handles ${action}, like the panel did`);
  }
  assert.match(js, /mapItemAction\(agentName, item, action\)/, '🎤/⌨ run on the agent widget, which owns the recorder');
  assert.match(js, /guard\([^;]*window\.las\.closeSession\(agentName, item\.sid\)/, 'closing a terminal goes through the security gate');
  assert.match(js, /guard\([^;]*removeMapElement\(agentName, item\.elementId\)/, 'a repo/url ✕ goes through the gate too');
  assert.doesNotMatch(js, /armConfirm/, 'no two-click confirm any more: the security mode decides');
  const widget = read('renderer', 'widget.js');
  assert.match(widget, /onMapItemAction\(\(item, action\) => \{\s*if \(action === 'mic'\) societyMic\(item\);\s*else if \(action === 'keyboard'\) societyKeyboard\(item\);/);
});

test('repo and url tiles: ✕/🚪 takes them off the map, ⧉ opens their link (disabled without one)', () => {
  const S = require('../renderer/society-model.js');
  assert.deepEqual(S.actionsFor({ kind: 'repo' }), ['exit', 'open']);
  assert.equal(S.describeAction({ kind: 'url', href: 'https://x.y' }, 'open').enabled, true);
  assert.equal(S.describeAction({ kind: 'repo', href: null }, 'open').enabled, false);
  assert.match(S.describeAction({ kind: 'repo' }, 'exit').title, /off the map/);
});

test('security gate: dangerous runs at once, safe asks in an in-window popup (never a browser dialog)', async () => {
  const views = read('renderer', 'society-views.js');
  assert.match(views, /async function guarded\(mode, question, action\) \{\s*if \(mode === 'safe' && !\(await confirmPopup\(question\)\)\) return undefined;\s*return action\(\);/);
  for (const f of ['society-views.js', 'map.js', 'widget.js']) {
    assert.doesNotMatch(read('renderer', f), /window\.confirm\(|[^.\w]confirm\(|alert\(/, `${f}: no browser dialogs — they freeze the window`);
  }
  const widget = read('renderer', 'widget.js');
  assert.doesNotMatch(widget, /armConfirm|CLOSE_CONFIRM_MS/);
  assert.match(widget, /guard\(`Unlink /);
  assert.match(read('renderer', 'index.html'), /<select id="securityMode">[\s\S]*value="dangerous"[\s\S]*value="safe"/);
  assert.match(read('main.js'), /ipcMain\.handle\('agent:set-security'/);
});

test('🙏 asks every terminal for its description; a mini widget is a bold title over a sliding description', () => {
  assert.match(read('renderer', 'map.html'), /id="toolsPill">\s*<button id="describeBtn"[^>]*>🙏</, 'in a pill inside the board, top left');
  assert.match(read('renderer', 'map.js'), /\$\('describeBtn'\)\.addEventListener\('click', askDescriptions\)/);
  assert.match(read('renderer', 'map.js'), /requestSessionTitles\(agentName\)/, 'the same backend request the children list uses');
  const views = read('renderer', 'society-views.js');
  assert.match(views, /scrollLine\('mw-runtime', item\.label\)/);
  assert.match(views, /scrollLine\('mw-detail', item\.detail\)/);
  assert.match(views, /addEventListener\('mouseenter', \(\) => marquee\(w, true\)\)/);
  const css = read('renderer', 'widget.css');
  assert.match(css, /\.mw-runtime \{[^}]*font-weight: 800/);
  assert.match(css, /\.mw-detail \{[^}]*font-size: 10px/);
  assert.match(css, /@keyframes mw-marquee/);
});
