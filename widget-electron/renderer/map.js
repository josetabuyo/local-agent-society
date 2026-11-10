'use strict';

/**
 * The map window (docs/adr/0007) — the society panel's 2D board in a widget
 * of its own: the agent's color glass, the same mini widgets, draggable, one
 * board (no grouping), and the same button bar on double-click or hold
 * (🚪 ⚙ ⧉ 🔊 ⌨ 🎤 ⌖ 📄, per kind — society-model.js ACTIONS_BY_KIND). 🎤 and ⌨
 * run on the agent's own widget, which owns the recorder and the keyboard.
 * Every tile also has a ✕: a terminal or command closes, a friend's widget
 * closes, a repo or URL leaves the map — straight away in dangerous mode, after
 * a popup in safe mode (security_mode, `las agent security`). Elements are added
 * with `las map add`. Canvas/List is the only display choice.
 */
(function () {
  const M = window.LasMap;
  const S = window.LasSociety;
  const V = window.LasSocietyViews;
  const params = new URLSearchParams(location.search);
  const agentName = params.get('agent') || '';
  const ownColor = /^#[0-9a-f]{6}$/i.test(params.get('color') || '') ? params.get('color') : S.DEFAULT_COLOR;
  const opacity = Math.max(0.15, Math.min(1, Number(params.get('opacity')) || 0.78));
  const REFRESH_MS = 5000;
  const VIEW_KEY = `las-map-view:${agentName}`;
  const POS_KEY = `las-map-positions:${agentName}`;

  const $ = (id) => document.getElementById(id);
  const el = (tag, className, text) => {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  };

  // ── the widget's glass: its color with the alpha baked in (widget.js applyColorVars) ──
  function applyColor() {
    const n = parseInt(ownColor.slice(1), 16);
    const rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    const root = document.documentElement.style;
    root.setProperty('--widget-bg', `rgba(${rgb.join(', ')}, ${opacity})`);
    root.setProperty('--text-fill', `rgba(20, 20, 20, ${opacity})`);
    root.setProperty('--btn-fill', `rgba(0, 0, 0, ${(0.16 * opacity).toFixed(3)})`);
    const dark = S.luminance(ownColor) < 0.5;
    root.setProperty('--map-text', dark ? 'rgba(245, 245, 245, 0.95)' : 'rgba(20, 20, 20, 0.92)');
    root.setProperty('--map-tint', dark ? 'rgba(255, 255, 255, 0.14)' : 'rgba(0, 0, 0, 0.07)');
    root.setProperty('--map-border', dark ? 'rgba(255, 255, 255, 0.35)' : 'rgba(0, 0, 0, 0.25)');
  }

  // ── per-viewer conveniences, never shared state ──
  const store = {
    get(key, fallback) {
      try { return { ...fallback, ...JSON.parse(localStorage.getItem(key) || '{}') }; } catch { return { ...fallback }; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private storage: memory only */ }
    },
  };
  const DEFAULT_VIEW = { layout: 'canvas' };
  const view = store.get(VIEW_KEY, DEFAULT_VIEW);
  const positions = store.get(POS_KEY, {});
  const saveView = () => store.set(VIEW_KEY, view);
  let items = [];

  // ── data ────────────────────────────────────────────────────────────────
  async function refresh() {
    const [sessions, friends, map] = await Promise.all([
      window.las.getAgentSessions(agentName).catch(() => null),
      window.las.getFriends(agentName).catch(() => null),
      window.las.getMap(agentName).catch(() => null),
    ]);
    const friendRows = (friends && friends.friends) || [];
    const colors = Object.fromEntries(friendRows.filter((f) => f.color).map((f) => [f.name, f.color]));
    // Each local friend's own mute (its widget prefs), for the 🔊 in its button bar.
    const muted = Object.fromEntries(await Promise.all(friendRows.filter((f) => !/@/.test(f.name)).map(async (f) => {
      try { return [f.name, !!((await window.las.getPrefs(f.name)) || {}).mute]; } catch { return [f.name, false]; }
    })));
    const next = M.buildMapItems({
      agentName,
      sessions: (sessions && sessions.sessions) || [],
      friends: friendRows.map((f) => ({ ...f, muted: muted[f.name] === true })),
      elements: (map && map.elements) || [],
      colorOf: (n) => (n === agentName ? ownColor : colors[n]),
    });
    // Redraw only when something changed: a redraw mid-drag would drop the tile.
    if (JSON.stringify(next) === JSON.stringify(items)) return;
    items = next;
    render();
  }

  // ── drawing ─────────────────────────────────────────────────────────────
  /** The agent's security mode (docs/adr/0007 §4), re-read before each destructive action. */
  async function securityMode() {
    try {
      const view = await window.las.getAgentConfig(agentName);
      return view && view.security_mode === 'safe' ? 'safe' : 'dangerous';
    } catch {
      return 'dangerous';
    }
  }

  /** dangerous: run now. safe: the popup asks first. */
  async function guard(question, action) {
    return V.guarded(await securityMode(), question, action);
  }

  function closeTitle(item) {
    if (item.kind === 'friend') return item.remote ? `${item.agent}'s widget lives on ${item.remote}` : `Close ${item.agent}'s widget`;
    if (item.kind === 'repo' || item.kind === 'url') return 'Take it off the map';
    return item.kind === 'command' ? 'Stop this command' : 'Close this terminal';
  }

  async function onClose(item) {
    if (item.kind === 'friend') {
      if (item.remote || item.widgetClosed) return;
      await guard(`Close ${item.agent}'s widget?`, () => window.las.closeAgentWidget(item.agent));
    } else if (item.kind === 'repo' || item.kind === 'url') {
      await guard(`Take “${item.label}” off the map?`, () => window.las.removeMapElement(agentName, item.elementId));
    } else {
      await guard(item.kind === 'command' ? `Stop the command “${item.detail}”?` : `Close this ${item.runtime} terminal?`, () => window.las.closeSession(agentName, item.sid));
    }
    refresh();
  }

  /** What a tile's button does — the same meaning as in the widget's panel (widget.js societyHandlers). */
  async function onAction(item, action, button, event) {
    if (action === 'exit') return onClose(item);
    if (action === 'mic' || action === 'keyboard') return window.las.mapItemAction(agentName, item, action);
    if (action === 'open') {
      if (item.kind === 'repo' || item.kind === 'url') return item.href && window.las.openUrl(item.href);
      const how = event && event.type === 'contextmenu' ? 'folder' : 'terminal';
      return window.las.openAgent(item.agent, how);
    }
    if (action === 'settings') {
      const host = button.closest('.tile-popup') || button;
      const r = host.getBoundingClientRect();
      V.closeTilePopup();
      return window.las.showAgentSettings(item.agent, { x: window.screenX + r.left, y: window.screenY + r.top, width: r.width, height: r.height, cover: true });
    }
    if (action === 'speaker') {
      await window.las.setPrefs(item.agent, { mute: !item.muted });
      return refresh();
    }
    if (action === 'find') return window.las.findSession(agentName, item.sid);
    if (action === 'log') return window.las.openSessionLog(item.detached && item.detached.log);
    if (action === 'unlink') {
      await guard(`Unlink ${item.agent} from ${agentName}'s friends?`, () => window.las.linkFriend(agentName, item.agent, false));
      return refresh();
    }
    return undefined;
  }

  const handlers = {
    onAction,
    onOpen: (item) => item.href && window.las.openUrl(item.href),
    onClose,
    closeTitle,
    onMove(key, pos) {
      positions[key] = pos;
      store.set(POS_KEY, positions);
    },
  };

  /** List layout: the panel's own List row (chip, detail, its whole button bar). */
  function listRow(item) {
    return V.listRow(item, handlers);
  }

  function render() {
    const host = $('map');
    host.replaceChildren();
    host.className = `map-body layout-${view.layout}`;
    const box = el('div', 'map-board');
    host.append(box);
    const empty = 'Nothing on this map yet — las map add repo PATH · las map add url URL';
    if (view.layout === 'list') {
      for (const item of items) box.append(listRow(item));
      if (!items.length) box.append(el('div', 'society-empty map-list-empty', empty));
    } else {
      V.renderPanel(box, items, positions, handlers, { empty });
    }
    for (const b of $('layoutSeg').querySelectorAll('button')) b.classList.toggle('active', b.dataset.value === view.layout);
  }

  $('layoutSeg').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    view.layout = b.dataset.value;
    saveView();
    render();
  });
  $('closeBtn').addEventListener('click', () => window.close());

  // ── start ───────────────────────────────────────────────────────────────
  document.title = `Map — ${agentName}`;
  $('agentName').textContent = agentName;
  applyColor();
  render();
  refresh();
  setInterval(refresh, REFRESH_MS);
  // The board is laid out for the window's width: follow a resize.
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 120);
  });
})();
