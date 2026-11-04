'use strict';

// The society drawer's shared model (renderer/society-model.js): sessions
// (terminals, commands) and las-friends as ONE list of items, the same two
// actions on every item, and the 2D panel layout. Both views (List, Panel)
// draw from this; widget.js only decides what an action does.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../renderer/society-model.js');

const ROOT = path.resolve(__dirname, '..');
const read = (...p) => fs.readFileSync(path.join(ROOT, ...p), 'utf8');

const colors = { Me: '#112233', Vortexia: '#f0e0a0' };
const colorOf = (n) => colors[n];

test('buildItems: sessions first (terminal vs detached command), then friends in file order, each with its agent color', () => {
  const items = M.buildItems({
    agentName: 'Me',
    sessions: [
      { sid: 'claude-ab12', runtime: 'claude', title: 'Las-friends', default: true },
      { sid: 'echo-cd34', runtime: 'echo', intelligent: false, detached: { log: '/tmp/x.log' } },
    ],
    friends: [
      { name: 'Vortexia', registered: true, sessions: 1, mutual: true },
      { name: 'Ghost', registered: false },
    ],
    colorOf,
  });
  assert.deepEqual(items.map((i) => [i.kind, i.key]), [
    ['terminal', 'session:claude-ab12'],
    ['command', 'session:echo-cd34'],
    ['friend', 'friend:Vortexia'],
    ['friend', 'friend:Ghost'],
  ]);
  assert.equal(items[0].color, '#112233', 'own sessions wear the own color');
  assert.equal(items[0].detail, 'Las-friends');
  assert.equal(items[1].detail, 'cd34', 'no title -> the short sid');
  assert.equal(items[2].color, '#f0e0a0');
  assert.equal(items[2].detail, '1 session · mutual');
  assert.equal(items[3].color, M.DEFAULT_COLOR, 'unknown color -> default');
  assert.equal(items[3].detail, 'not registered');
});

test('every item offers the same actions; describeAction says what they mean and when they cannot run', () => {
  assert.deepEqual(M.ACTIONS, ['mic', 'exit']);
  const [term, , friend, ghost] = M.buildItems({
    agentName: 'Me',
    sessions: [{ sid: 'claude-1', runtime: 'claude' }, { sid: 'p-2', runtime: 'p', detached: {} }],
    friends: [{ name: 'Vortexia', inactive: true }, { name: 'Ghost', registered: false }],
  });
  assert.equal(M.describeAction(term, 'exit').confirm, true, 'closing a terminal takes a second click');
  assert.match(M.describeAction(term, 'mic').title, /claude session/);
  assert.equal(M.describeAction(friend, 'mic').enabled, true);
  assert.equal(M.describeAction(friend, 'exit').enabled, false, 'its widget is already closed');
  assert.equal(M.describeAction(ghost, 'mic').enabled, false, 'an unregistered friend cannot be dictated to');
});

test('chipColors picks readable text from the luminance of the agent color', () => {
  assert.equal(M.chipColors('#ffffff').color, '#141414');
  assert.equal(M.chipColors('#101010').color, '#f4f4f4');
  assert.match(M.chipColors('#ff0000', 0.5).background, /rgba\(255, 0, 0, 0\.5\)/);
});

test('layout: saved spots win (clamped inside), new items take free grid slots that never overlap', () => {
  const items = ['a', 'b', 'c', 'd'].map((k) => ({ key: k }));
  const pos = M.layout(items, { a: { x: 0, y: 0 }, c: { x: 9999, y: -50 }, gone: { x: 1, y: 1 } }, 300, 136);
  assert.deepEqual(pos.a, { x: 0, y: 0 });
  assert.deepEqual(pos.c, { x: 300 - M.TILE, y: 0 });
  assert.equal(pos.gone, undefined, 'positions of removed items are dropped');
  const all = Object.values(pos);
  for (let i = 0; i < all.length; i++) {
    for (let j = i + 1; j < all.length; j++) {
      assert.ok(Math.abs(all[i].x - all[j].x) >= M.TILE || Math.abs(all[i].y - all[j].y) >= M.TILE, `tiles ${i} and ${j} overlap`);
    }
  }
});

test('panelHeight grows to fit the lowest tile', () => {
  assert.equal(M.panelHeight({}, 100), 100);
  assert.equal(M.panelHeight({ a: { x: 0, y: 200 } }, 100), 200 + M.TILE);
});

test('wiring: the page loads the model and views before widget.js, and widget.js draws only through them', () => {
  const html = read('renderer', 'index.html');
  const order = ['society-model.js', 'society-views.js', 'widget.js'].map((f) => html.indexOf(`src="${f}"`));
  assert.ok(order.every((i) => i > 0) && order[0] < order[1] && order[1] < order[2], 'script order');
  const widget = read('renderer', 'widget.js');
  assert.match(widget, /LasSociety\.buildItems\(/);
  assert.match(widget, /LasSocietyViews\.renderPanel\(/);
  assert.match(widget, /LasSocietyViews\.listRow\(/);
  assert.ok(JSON.parse(read('package.json')).build.files.includes('renderer/**/*'), 'the new renderer files ship in the app');
});

test('wiring: the per-item mic sends where its recording started, not to this agent', () => {
  const widget = read('renderer', 'widget.js');
  assert.match(widget, /const destination = micDestination;/);
  assert.match(widget, /sendDictation\(destination, result\.text\)/);
  const preload = read('preload.js');
  assert.match(preload, /sendHuman: \(toName, text, opts\) => ipcRenderer\.invoke\('vortexia:send', toName, text, opts/);
  const main = read('main.js');
  assert.match(main, /body\.session = opts\.session/);
  for (const ch of ['agent:friends', 'agent:friend-link', 'agent:names', 'agent:close-widget']) {
    assert.ok(main.includes(`ipcMain.handle('${ch}'`), `${ch} handled in main`);
  }
});
