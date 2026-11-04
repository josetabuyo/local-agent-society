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

  const KIND_ICONS = { terminal: '\u{1F4BB}', command: '⚙️', friend: '\u{1F91D}' };

  /** Every item offers the same two actions, so a view never special-cases a kind. */
  const ACTIONS = ['mic', 'exit'];
  const ACTION_ICONS = { mic: '\u{1F3A4}', exit: '\u{1F6AA}' };

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
      detail: f.registered === false ? 'not registered' : `${f.sessions || 0} session${f.sessions === 1 ? '' : 's'}${f.mutual ? ' · mutual' : ''}`,
      color,
      mutual: !!f.mutual,
      registered: f.registered !== false,
      widgetClosed: !!f.inactive,
    };
  }

  /**
   * @param {{agentName: string, sessions?: object[], friends?: object[], colorOf?: (name: string) => string}} input
   * @returns {object[]} sessions first (most recently used first, as the backend orders them), then friends in file order
   */
  function buildItems({ agentName, sessions = [], friends = [], colorOf = () => DEFAULT_COLOR }) {
    const own = colorOf(agentName) || DEFAULT_COLOR;
    return [
      ...sessions.map((s) => sessionItem(agentName, s, own)),
      ...friends.map((f) => friendItem(f, colorOf(f.name) || DEFAULT_COLOR)),
    ];
  }

  /** What each action means for this item — the tooltip, and whether it can run now. */
  function describeAction(item, action) {
    if (action === 'mic') {
      if (item.kind === 'friend') return { title: `Dictate a message to ${item.agent}`, enabled: item.registered };
      return { title: `Dictate to this ${item.runtime} session only`, enabled: true };
    }
    if (action === 'exit') {
      if (item.kind === 'friend') {
        return item.widgetClosed
          ? { title: `${item.agent}'s widget is already closed`, enabled: false }
          : { title: `Close ${item.agent}'s widget (it stays here, in the panel)`, enabled: item.registered };
      }
      return { title: item.kind === 'command' ? 'Stop this command' : 'Close this terminal', enabled: true, confirm: true };
    }
    return { title: action, enabled: false };
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

  return { DEFAULT_COLOR, KIND_ICONS, ACTIONS, ACTION_ICONS, TILE, GAP, buildItems, describeAction, chipColors, luminance, layout, clamp, panelHeight };
});
