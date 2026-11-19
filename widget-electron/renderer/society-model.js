'use strict';

/**
 * The society around one agent, as one list of items — the single model
 * every view draws from (the children drawer's List tab, its 2D Panel tab,
 * and whatever view comes next). No DOM here: views only render items and
 * call back with (item, actionId); what an action DOES lives in widget.js.
 *
 * Three kinds of item:
 *   terminal — a connected session with a terminal (claude, codex, shell)
 *   command  — a detached session (`las <command…>`, docs/adr/0006)
 *   friend   — a las-friend: an agent listed in this agent's `friends`
 *              (with `global: true`: one agent of the Mac on the global panel)
 *
 * Loaded twice: as a plain <script> in the renderer (window.LasSociety) and
 * with require() from the node tests.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LasSociety = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const DEFAULT_COLOR = '#90c060';

  // Only sessions carry an icon (top-left, next to their runtime); an agent — a friend, or a widget at icon size — is just its name.
  const KIND_ICONS = { terminal: '\u{1F4BB}', command: '⚙️', repo: '\u{1F4E6}', url: '\u{1F517}' };

  /**
   * The actions every item offers — the actions it offers, in the order of a
   * widget's own button bar (door first, mic last), minus 👥 children: a
   * friend gets that friend's whole button bar, a session what a single
   * terminal or command can do. A view draws whatever this returns.
   */
  const ACTIONS_BY_KIND = {
    // 🗄 archive: put it away — off the map, still at hand (the map's Archive).
    friend: ['exit', 'settings', 'open', 'speaker', 'keyboard', 'mic', 'archive'],
    terminal: ['exit', 'find', 'keyboard', 'mic'],
    command: ['exit', 'log', 'keyboard', 'mic'],
    // The map's own elements (docs/adr/0007): take it off the map, open its link.
    repo: ['exit', 'open', 'archive'],
    url: ['exit', 'open', 'archive'],
  };
  /** One agent on the global panel (`las map global`): its own widget's bar, its map, the society's archive. */
  const GLOBAL_ACTIONS = ['exit', 'settings', 'open', 'map', 'speaker', 'archive'];
  /** Actions shared by every kind. */
  const ACTIONS = ['exit', 'keyboard', 'mic'];
  const ACTION_ICONS = {
    exit: '✕', settings: '⚙', open: '⧉', speaker: '\u{1F50A}', muted: '\u{1F507}',
    keyboard: '⌨', mic: '\u{1F3A4}', find: '⌖', log: '\u{1F4C4}', archive: '\u{1F5C4}', map: '\u{1F5FA}',
  };

  function actionsFor(item) {
    if (item && item.global) return GLOBAL_ACTIONS;
    return ACTIONS_BY_KIND[item && item.kind] || ACTIONS;
  }

  /** The icon an action shows for this item (the speaker follows the item's mute). */
  function actionIcon(item, action) {
    if (action === 'speaker' && item.muted) return ACTION_ICONS.muted;
    return ACTION_ICONS[action] || action;
  }

  function shortSid(sid) {
    return String(sid).split('-')[1] || String(sid);
  }

  function sessionItem(agentName, s, color) {
    const kind = s.detached ? 'command' : 'terminal';
    return {
      key: `session:${s.sid}`,
      kind,
      agent: agentName,
      sid: s.sid,
      runtime: s.runtime || '?',
      label: s.runtime || '?',
      detail: s.title || shortSid(s.sid),
      color,
      intelligent: s.intelligent !== false,
      isDefault: !!s.default,
      detached: s.detached || null,
    };
  }

  function friendItem(f, color) {
    return {
      key: `friend:${f.name}`,
      kind: 'friend',
      agent: f.name,
      label: f.name,
      // A friend on another machine (Name@env, over vortex-relay): its sessions and widget live there.
      detail: f.remote ? `on ${f.remote} · vortex-relay`
        : f.registered === false ? 'not registered' : `${f.sessions || 0} session${f.sessions === 1 ? '' : 's'}${f.mutual ? ' · mutual' : ''}`,
      remote: f.remote || null,
      color,
      mutual: !!f.mutual,
      registered: f.registered !== false,
      widgetClosed: !!f.inactive,
      muted: !!f.muted,
    };
  }

  /** An agent's own widget at icon size: the same mini widget a friend gets in a panel. */
  function agentItem(name, color) {
    return { key: `agent:${name}`, kind: 'agent', agent: name, label: name, detail: '', color: color || DEFAULT_COLOR };
  }

  /**
   * @param {{agentName: string, sessions?: object[], friends?: object[], colorOf?: (name: string) => string}} input
   * @returns {object[]} sessions first (most recently used first, as the backend orders them), then friends in file order
   */
  function buildItems({ agentName, sessions = [], friends = [], colorOf = () => DEFAULT_COLOR, mutedOf = () => false }) {
    const own = colorOf(agentName) || DEFAULT_COLOR;
    return [
      ...sessions.map((s) => sessionItem(agentName, s, own)),
      ...friends.map((f) => friendItem({ ...f, muted: f.muted || mutedOf(f.name) }, colorOf(f.name) || DEFAULT_COLOR)),
    ];
  }

  /** What each action means for this item — the tooltip, and whether it can run now. */
  function describeAction(item, action) {
    const friend = item.kind === 'friend';
    // A friend on another machine: its widget, folder and prefs live there — only words travel.
    const local = friend && item.registered && !item.remote;
    const away = friend && item.remote ? ` — ${item.agent} lives on ${item.remote}` : '';
    if (action === 'settings') {
      return { title: local ? `${item.agent}'s settings — brings its widget here, settings open` : `Settings${away || ' — not registered'}`, enabled: local };
    }
    if ((item.kind === 'repo' || item.kind === 'url') && (action === 'open' || action === 'exit')) {
      if (action === 'exit') return { title: 'Take it off the map', enabled: true };
      return { title: item.href ? `Open ${item.href}` : 'No link — this repo has no GitHub remote', enabled: !!item.href };
    }
    if (action === 'open') {
      return { title: local ? `Open a terminal at ${item.agent}'s folder (right-click: the folder)` : `Open${away || ' — not registered'}`, enabled: local };
    }
    if (action === 'speaker') {
      if (!local) return { title: `Mute${away || ' — not registered'}`, enabled: false };
      return { title: item.muted ? `Unmute ${item.agent}` : `Mute ${item.agent}`, enabled: true };
    }
    if (action === 'keyboard') {
      if (friend) return { title: `Type a message to ${item.agent}`, enabled: item.registered };
      return { title: `Type to this ${item.runtime} session only`, enabled: true };
    }
    if (action === 'map') return { title: `Open ${item.agent}'s map`, enabled: true };
    if (action === 'archive' && item.global) return { title: `Archive ${item.agent} — off the society, its widget closes (Archive here brings it back)`, enabled: true };
    if (action === 'archive') return { title: 'Put it in the archive — off the map, still at hand (🗄 on the map lists it)', enabled: true };
    if (action === 'find') return { title: 'Find this terminal — bring it to the front', enabled: true };
    if (action === 'log') return { title: "Open this background process's log", enabled: !!(item.detached && item.detached.log) };
    if (action === 'mic') {
      if (item.kind === 'friend') return { title: `Dictate a message to ${item.agent}`, enabled: item.registered };
      return { title: `Dictate to this ${item.runtime} session only`, enabled: true };
    }
    if (action === 'exit') {
      // A popup offers the choices (closeChoices): close its widget, archive, unfriend, delete.
      if (item.global) return { title: `Close ${item.agent}'s widget, archive it or delete it…`, enabled: true };
      if (item.kind === 'friend') return { title: `Close ${item.agent}'s widget, archive it, unfriend it or delete it…`, enabled: true };
      return { title: item.kind === 'command' ? 'Stop this command' : 'Close this terminal', enabled: true, confirm: true };
    }
    return { title: action, enabled: false };
  }

  // ── the global panel and the ✕ popup ─────────────────────────────────────
  /** Every node of a /society/tree, depth first, each with its `parent` name (or null). */
  function flattenTree(tree) {
    const out = [];
    const walk = (node, parent) => {
      out.push({ node, parent });
      for (const child of node.children || []) walk(child, node.name);
    };
    for (const root of (tree && tree.agents) || []) walk(root, null);
    return out;
  }

  /** The agents of `tree` other than `except` whose `friends` list `name`. */
  function linkedBy(tree, name, except = null) {
    return flattenTree(tree).map((r) => r.node).filter((n) => n.name !== except && (n.friends || []).includes(name)).map((n) => n.name);
  }

  /** Shown nowhere: off the main screen and nobody's friend — it can only be found on the global panel. */
  function isHidden(tree, node) {
    return node.main_screen === false && linkedBy(tree, node.name).length === 0;
  }

  /** The global panel: every agent of the Mac as a mini widget, parents before their subordinates. */
  function buildGlobalItems(tree) {
    return flattenTree(tree).map(({ node, parent }) => {
      const sessions = Array.isArray(node.sessions) ? node.sessions.length : 0;
      const hidden = isHidden(tree, node);
      const where = hidden ? '⚠ shown nowhere — off the main screen, nobody\'s friend'
        : node.short_description || (parent ? `in ${parent}` : `${sessions} session${sessions === 1 ? '' : 's'}`);
      return {
        key: `agent:${node.name}`, kind: 'friend', global: true, agent: node.name, label: node.name, detail: where,
        parent, hidden, mainScreen: node.main_screen !== false, color: node.color || DEFAULT_COLOR,
        registered: true, remote: null, mutual: false, widgetClosed: !!node.inactive, muted: false, sessions,
      };
    });
  }

  /**
   * What the ✕ on a friend (or an agent of the global panel) can do, for the
   * popup: [{id, label, detail, danger?}]. `owner` is the agent whose panel
   * it is (null on the global panel); `tree` (/society/tree, may be null)
   * says whether unfriending would leave it shown nowhere.
   */
  function closeChoices(item, owner, tree) {
    const local = item.registered && !item.remote;
    const choices = [];
    if (local && !item.widgetClosed) {
      choices.push({ id: 'close', label: 'Close its widget', detail: owner ? `${item.agent} stays in ${owner}'s panel` : 'nothing else changes' });
    }
    if (owner) {
      choices.push({ id: 'archive', label: `Archive it in ${owner}`, detail: `off this panel, kept in ${owner}'s Archive — ↩ brings it back` });
      const node = tree && local ? flattenTree(tree).map((r) => r.node).find((n) => n.name === item.agent) : null;
      const orphan = !!node && node.main_screen === false && linkedBy(tree, item.agent, owner).length === 0;
      choices.push({
        id: orphan ? 'unfriend-archive' : 'unfriend',
        label: 'Remove from friends',
        detail: orphan
          ? `${item.agent} is off the main screen and nobody else's friend — it goes to the society's archive too, or it would show nowhere`
          : `only ${owner}'s link goes; ${item.agent} stays in the society`,
      });
    } else {
      choices.push({ id: 'archive-agent', label: 'Archive the agent', detail: 'off the society, its widget closes — ↩ in Archive brings it back' });
    }
    if (local) {
      choices.push({ id: 'delete', label: `Delete ${item.agent}`, danger: true,
        detail: 'unregisters it from LAS on this Mac — its folder and files stay; a session opened there registers it again' });
    }
    return choices;
  }

  /** WCAG relative luminance of '#rrggbb', 0..1. */
  function luminance(hex) {
    const n = parseInt(String(hex || DEFAULT_COLOR).replace('#', ''), 16) || 0;
    const lin = (c) => {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  }

  /** Background + readable text color for a chip or mini sticky tinted with `hex`. */
  function chipColors(hex, alpha = 0.85) {
    const n = parseInt(String(hex || DEFAULT_COLOR).replace('#', ''), 16) || 0;
    const bg = `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
    return { background: bg, color: luminance(hex) > 0.35 ? '#141414' : '#f4f4f4' };
  }

  // ── 2D panel layout ──────────────────────────────────────────────────────

  const TILE = 64;
  const GAP = 8;

  /** Keep a tile fully inside the area. */
  function clamp(pos, width, height) {
    return {
      x: Math.max(0, Math.min(Math.round(pos.x), Math.max(0, width - TILE))),
      y: Math.max(0, Math.min(Math.round(pos.y), Math.max(0, height - TILE))),
    };
  }

  function overlaps(a, b) {
    return Math.abs(a.x - b.x) < TILE && Math.abs(a.y - b.y) < TILE;
  }

  /**
   * Where every item sits: its saved position when it has one (clamped into
   * the area), otherwise the first free grid slot — reading order, skipping
   * slots a saved tile covers. Saved positions of items that are gone are
   * simply not returned.
   * @returns {Object<string, {x: number, y: number}>}
   */
  function layout(items, saved, width, height) {
    const out = {};
    const placed = [];
    for (const item of items) {
      const s = saved && saved[item.key];
      if (s && Number.isFinite(s.x) && Number.isFinite(s.y)) {
        out[item.key] = clamp(s, width, height);
        placed.push(out[item.key]);
      }
    }
    const cols = Math.max(1, Math.floor((width + GAP) / (TILE + GAP)));
    let slot = 0;
    for (const item of items) {
      if (out[item.key]) continue;
      let pos;
      do {
        pos = { x: (slot % cols) * (TILE + GAP), y: Math.floor(slot / cols) * (TILE + GAP) };
        slot += 1;
      } while (placed.some((p) => overlaps(p, pos)) && slot < 500);
      out[item.key] = clamp(pos, width, Math.max(height, pos.y + TILE));
      placed.push(out[item.key]);
    }
    return out;
  }

  /** Height the panel needs so every tile is visible (at least `min`). */
  function panelHeight(positions, min) {
    const bottom = Object.values(positions).reduce((m, p) => Math.max(m, p.y + TILE), 0);
    return Math.max(min, bottom);
  }

  return { DEFAULT_COLOR, KIND_ICONS, ACTIONS, ACTIONS_BY_KIND, GLOBAL_ACTIONS, ACTION_ICONS, actionsFor,
    flattenTree, linkedBy, isHidden, buildGlobalItems, closeChoices, actionIcon, TILE, GAP, buildItems, agentItem, describeAction, chipColors, luminance, layout, clamp, panelHeight };
});
