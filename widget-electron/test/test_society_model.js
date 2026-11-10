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

test('every item offers its actions; describeAction says what they mean and when they cannot run', () => {
  assert.deepEqual(M.ACTIONS, ['exit', 'keyboard', 'mic']);
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
  assert.doesNotMatch(widget, /LasSocietyViews\.renderPanel\(/, 'the 2D board left the drawer for the map window (map.js)');
  assert.match(read('renderer', 'map.js'), /V\.renderPanel\(/);
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

test('a friend on another machine (Name@env) can be dictated to but its widget cannot be closed from here', () => {
  const [item] = M.buildItems({ agentName: 'RelayRobotics', friends: [{ name: 'coach@uy-mac', registered: true, remote: 'uy-mac', sessions: null, mutual: null }] });
  assert.equal(item.detail, 'on uy-mac · vortex-relay');
  assert.equal(M.describeAction(item, 'mic').enabled, true);
  assert.equal(M.describeAction(item, 'exit').enabled, false);
});

test('a friend tile offers that friend\'s whole button bar, minus 👥 children, in the widget\'s order', () => {
  const [term, cmd, friend] = M.buildItems({
    agentName: 'Me',
    sessions: [{ sid: 'claude-1', runtime: 'claude' }, { sid: 'p-2', runtime: 'p', detached: { log: '/tmp/p.log' } }],
    friends: [{ name: 'Vortexia', sessions: 1 }],
    mutedOf: (n) => n === 'Vortexia',
  });
  assert.deepEqual(M.actionsFor(friend), ['exit', 'settings', 'open', 'speaker', 'keyboard', 'mic']);
  assert.ok(!M.actionsFor(friend).includes('children'), 'no friends/children button inside a friend');
  assert.deepEqual(M.actionsFor(term), ['exit', 'find', 'keyboard', 'mic']);
  assert.deepEqual(M.actionsFor(cmd), ['exit', 'log', 'keyboard', 'mic']);
  for (const a of M.actionsFor(friend)) assert.equal(M.describeAction(friend, a).enabled, true, `${a} runs on a local friend`);
  assert.equal(friend.muted, true);
  assert.equal(M.actionIcon(friend, 'speaker'), M.ACTION_ICONS.muted, 'a muted friend shows 🔇');
  assert.match(M.describeAction(friend, 'speaker').title, /Unmute Vortexia/);
  assert.equal(M.describeAction(cmd, 'log').enabled, true);
  assert.match(M.describeAction(term, 'keyboard').title, /claude session/);
});

test('a remote or unregistered friend: only words travel — its widget buttons are disabled', () => {
  const [remote, ghost] = M.buildItems({ agentName: 'Me', friends: [{ name: 'coach@uy-mac', remote: 'uy-mac' }, { name: 'Ghost', registered: false }] });
  for (const a of ['settings', 'open', 'speaker']) {
    assert.equal(M.describeAction(remote, a).enabled, false, `${a} is not reachable over vortex-relay`);
    assert.equal(M.describeAction(ghost, a).enabled, false);
  }
  assert.equal(M.describeAction(remote, 'keyboard').enabled, true);
  assert.equal(M.describeAction(ghost, 'keyboard').enabled, false);
});

test('the mini widget: an agent is only its name; a session has its icon + runtime on top, title/command below', () => {
  assert.equal(M.KIND_ICONS.friend, undefined, 'no emoji on a friend');
  assert.equal(M.KIND_ICONS.agent, undefined);
  assert.ok(M.KIND_ICONS.terminal && M.KIND_ICONS.command);
  const me = M.agentItem('Me', '#123456');
  assert.deepEqual([me.kind, me.label, me.color], ['agent', 'Me', '#123456']);
  const views = read('renderer', 'society-views.js');
  assert.match(views, /function miniWidget\(item/);
  assert.match(views, /const t = miniWidget\(item/, 'a panel tile IS a mini widget');
  assert.match(views, /'mw-head'[\s\S]{0,200}'mw-icon'[\s\S]{0,120}'mw-runtime'[\s\S]{0,200}'mw-detail'/);
  assert.match(views, /el\('div', 'mw-name', item\.label\)/);
  const widget = read('renderer', 'widget.js');
  assert.match(widget, /LasSocietyViews\.miniWidget\(item/, 'a widget at icon size draws the same component');
});

test('size toggle: double-click on the top strip switches sticky ↔ icon; a resize never does', () => {
  const main = read('main.js');
  assert.match(main, /const ICON_SIZE = 64;/);
  assert.equal(M.TILE, 64, 'icon size = a panel mini widget');
  assert.doesNotMatch(main, /resize-end|settleResize/, 'no size snapping on resize');
  assert.match(main, /ipcMain\.on\('window:toggle-icon'[\s\S]{0,300}setIconMode\(win\.agentName, !getPrefs\(win\.agentName\)\.iconMode\)/);
  assert.match(main, /if \(win\.agentName && getPrefs\(win\.agentName\)\.iconMode\) return;/, 'an icon has one size');
  assert.match(main, /setPrefs\(name, \{ stickySize: \{ width: b\.width, height: b\.height \} \}\)/, 'the sticky comes back at its own size');
  assert.match(main, /if \(prefs\.iconMode\) bounds = \{ \.\.\.bounds, width: ICON_SIZE, height: ICON_SIZE \}/, 'reopens at icon size');
  const widget = read('renderer', 'widget.js');
  assert.match(widget, /titleStripEl\.addEventListener\('dblclick', \(\) => window\.las\.toggleIconMode\(\)\)/);
  assert.match(widget, /if \(e\.clientY - r\.top < r\.height \/ 2\) window\.las\.toggleIconMode\(\);\n  else window\.las\.togglePopup\(\);/, 'icon: top half = full size, lower half = buttons');
  assert.match(widget, /!!prefs\.expandWhenHidden && !prefs\.iconMode/, 'an icon never balloons into a mosaic tile');
  const html = read('renderer', 'index.html');
  assert.match(html, /id="iconFace"/);
  assert.match(html, /id="titleStrip"/);
  assert.match(read('renderer', 'widget.css'), /\.title-strip \{[^}]*-webkit-app-region: no-drag/, 'a drag region would swallow the double-click');
});

test('the icon\'s popup: a window of its own with every face button; drawers grow it, never the icon', () => {
  const main = read('main.js');
  assert.match(main, /query: \{ agent: name, [^}]*role: 'popup'/);
  assert.match(main, /if \(win\.isPopup\) return placePopup\(win, expanded/, 'drawers grow the popup, re-placed around the icon');
  assert.match(main, /win\.isPopup && popups\.get\(win\.agentName\) === win\) return win\.agentName/, 'its mic/keyboard speak for the agent');
  assert.match(main, /if \(!win \|\| win\.isDestroyed\(\) \|\| win\.isPopup\) return;\n  const st = tileStateOf/, 'a popup is never a mosaic tile');
  assert.match(main, /recordingWindows\.has\(name\)\) return;/, 'never closed mid-dictation');
  const widget = read('renderer', 'widget.js');
  assert.match(widget, /document\.querySelector\('\.bar-left'\)\.prepend\(doorEl\)/, 'the 🚪 joins the bar too, first');
  // It is created hidden: a requestAnimationFrame there never runs, and the popup never showed.
  assert.match(widget, /if \(isPopup\) setTimeout\(reportPopupReady, 0\)/);
  assert.doesNotMatch(widget, /requestAnimationFrame\(reportPopupReady\)/);
  assert.match(main, /p\.isVisible\(\)\) \{ log\.warn\('popup'/, 'never left invisible');
  // A mini widget outside a panel: no resize, no grab hand.
  assert.match(main, /resizable: !prefs\.iconMode/);
  assert.match(main, /win\.setResizable\(!on\)/);
  assert.doesNotMatch(read('renderer', 'widget.css').match(/\.widget\.icon-mode \.icon-face \{[^}]*\}/)[0], /cursor: grab/);
  assert.match(widget, /if \(prefs\.iconMode && !isPopup\) return window\.las\.togglePopup\('settings'\)/);
  const css = read('renderer', 'widget.css');
  assert.match(css, /\.widget\.icon-mode > :not\(\.icon-face\)/);
  assert.match(css, /\.widget\.role-popup \.log/);
});

test('wiring: the tile bar floats above the tile, and every action is handled', () => {
  const views = read('renderer', 'society-views.js');
  assert.match(views, /el\('div', 'tile-popup'\)/);
  assert.match(views, /document\.body\.appendChild\(bar\)/, 'outside the panel square, so nothing clips it');
  assert.ok(!views.includes("'tile-menu'"), 'the old in-square menu is gone');
  const css = read('renderer', 'widget.css');
  assert.match(css, /\.tile-popup \{[^}]*position: fixed/);
  const widget = read('renderer', 'widget.js');
  for (const a of ['mic', 'keyboard', 'exit', 'settings', 'open', 'speaker', 'find', 'log']) {
    assert.ok(widget.includes(`action === '${a}'`), `${a} handled in societyHandlers`);
  }
  assert.match(widget, /sendDictation\(keyboardDestination, text\)/, 'the tile ⌨ sends where it was aimed');
  const main = read('main.js');
  assert.ok(main.includes("ipcMain.handle('agent:show-settings'"));
  assert.match(main, /webContents\.send\('prefs:changed', next\)/, 'a friend\'s mute is applied live by its window');
  const preload = read('preload.js');
  for (const k of ['onPrefsChanged', 'showAgentSettings', 'onOpenSettings']) assert.ok(preload.includes(`${k}:`), k);
  // ⚙ on a friend's mini widget: its settings in a popup right there — its own widget is not reopened.
  assert.match(main, /togglePopup\(name, 'settings', a\)/);
  assert.doesNotMatch(main.slice(main.indexOf("ipcMain.handle('agent:show-settings'")).slice(0, 800), /reopenWidget/);
  assert.match(widget, /const anchor = \{ x: window\.screenX \+ r\.left[^}]*cover: true \}/);
  assert.match(widget, /showAgentSettings\(item\.agent, anchor\)/);
});

test('wiring: a hold on a tile opens its floating bar (map window tiles)', () => {
  const views = read('renderer', 'society-views.js');
  assert.match(views, /LONG_PRESS_MS = 600/);
  assert.match(views, /hold = setTimeout\([\s\S]{0,120}openTilePopup\(t, item, handlers\)/);
});

test('every shipped script parses (a syntax error in main.js only shows up as a crash dialog at launch)', () => {
  const { execFileSync } = require('node:child_process');
  const path = require('node:path');
  for (const f of ['main.js', 'preload.js', 'tray.js', 'bubbles.js', 'renderer/widget.js', 'renderer/society-model.js', 'renderer/society-views.js', 'renderer/map-model.js', 'renderer/map.js']) {
    execFileSync(process.execPath, ['--check', path.join(__dirname, '..', f)]);
  }
});

test('the popup block runs at load before the reveal constants exist: it must not call setReveal (TDZ killed the whole popup)', () => {
  const widget = read('renderer', 'widget.js');
  const start = widget.indexOf('if (isPopup) {');
  const block = widget.slice(start, widget.indexOf('\n}\n', start));
  assert.doesNotMatch(block, /setReveal\(/);
  assert.ok(start < widget.indexOf('const REVEAL_TRACK_MS'), 'the block sits above the constants — keep it free of reveal calls');
  assert.match(widget, /setReveal\(isPopup \? 1 : 0\)/);
  assert.match(widget, /window\.addEventListener\('error', \(e\) => \{\n  window\.las\.log\('error', 'renderer'/, 'renderer errors reach widget.log');
});
