'use strict';

/**
 * The map's element types (docs/adr/0007) — a registry, not a fixed set of
 * kinds. Every element on an agent's map is one item of one type; the map
 * window draws them, counts them per type and hides the types the viewer
 * switched off. No DOM here.
 *
 * Items come from three sources and keep society-model.js's shape (key,
 * kind, label, detail, color):
 *   sessions → one type per runtime (claude, claudeRelay, codex, shell) or `command`
 *   friends  → `friend`
 *   elements → `repo`, `url` (added with `las map add`, GET /agents/{name}/map)
 *
 * A new type is one more entry in TYPES (and, if it comes from a new source,
 * one more line in buildMapItems). Its chip in the Display popover appears
 * by itself.
 *
 * Loaded as a plain <script> (window.LasMap) after society-model.js, and with
 * require() from the node tests.
 */
(function (root, factory) {
  const api = factory(typeof module === 'object' && module.exports ? require('./society-model') : root.LasSociety);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LasMap = api;
})(typeof self !== 'undefined' ? self : this, function (Society) {
  /**
   * The registry, in display order. `group` is a coarse family for "group by"
   * views; `match(item)` says whether an item is of this type.
   */
  const TYPES = [
    { id: 'claude', label: 'Claude Code', icon: '✳️', group: 'sessions', match: (i) => i.kind === 'terminal' && i.runtime === 'claude' },
    { id: 'claudeRelay', label: 'Claude Relay', icon: '✴️', group: 'sessions', match: (i) => i.kind === 'terminal' && /^claude.+/.test(i.runtime) },
    { id: 'codex', label: 'Codex', icon: '\u{1F9E0}', group: 'sessions', match: (i) => i.kind === 'terminal' && i.runtime === 'codex' },
    { id: 'shell', label: 'Shells', icon: '\u{1F41A}', group: 'sessions', match: (i) => i.kind === 'terminal' && i.runtime === 'shell' },
    { id: 'terminal', label: 'Other terminals', icon: '\u{1F4BB}', group: 'sessions', match: (i) => i.kind === 'terminal' },
    { id: 'command', label: 'Commands', icon: '⚙️', group: 'sessions', match: (i) => i.kind === 'command' },
    { id: 'friend', label: 'Friends', icon: '\u{1F91D}', group: 'agents', match: (i) => i.kind === 'friend' },
    { id: 'repo', label: 'Repos', icon: '\u{1F4E6}', group: 'tools', match: (i) => i.kind === 'repo' },
    { id: 'url', label: 'URLs', icon: '\u{1F517}', group: 'links', match: (i) => i.kind === 'url' },
  ];
  const BY_ID = Object.fromEntries(TYPES.map((t) => [t.id, t]));

  /** The id of the first type that matches `item` (the registry order decides ties: claude before claudeRelay before terminal). */
  function typeOf(item) {
    const t = TYPES.find((type) => type.match(item));
    return t ? t.id : 'terminal';
  }

  function elementItem(agentName, row, color) {
    if (row.type === 'repo') {
      const detail = !row.exists ? 'missing — not a git folder'
        : [row.github || 'no GitHub remote', row.branch].filter(Boolean).join(' · ');
      return {
        key: `map:${row.id}`, elementId: row.id, kind: 'repo', agent: agentName, label: row.label, detail, color,
        path: row.abs_path || row.path, github: row.github || null, exists: !!row.exists,
        href: row.github ? `https://github.com/${row.github}` : null,
      };
    }
    let host = row.url;
    try { host = new URL(row.url).host; } catch { /* keep the raw url */ }
    return { key: `map:${row.id}`, elementId: row.id, kind: 'url', agent: agentName, label: row.label, detail: host, color, href: row.url };
  }

  /**
   * Every item on `agentName`'s map, each tagged with `type`.
   * @param {{agentName: string, sessions?: object[], friends?: object[], elements?: object[], colorOf?: (name: string) => string}} input
   */
  function buildMapItems({ agentName, sessions = [], friends = [], elements = [], colorOf = () => Society.DEFAULT_COLOR }) {
    const own = colorOf(agentName) || Society.DEFAULT_COLOR;
    const items = [
      ...Society.buildItems({ agentName, sessions, friends, colorOf }),
      ...elements.map((row) => elementItem(agentName, row, own)),
    ];
    return items.map((item) => {
      const type = typeOf(item);
      // A session's mini widget shows its type's icon, so a Claude, a Codex and a shell read apart.
      return { ...item, type, icon: BY_ID[type].icon };
    });
  }

  /** How many items of each type — every registered type present, zero included. */
  function countByType(items) {
    const counts = Object.fromEntries(TYPES.map((t) => [t.id, 0]));
    for (const item of items) counts[item.type] = (counts[item.type] || 0) + 1;
    return counts;
  }

  /** The items whose type is not in `hidden` (an array or Set of type ids). */
  function visible(items, hidden) {
    const off = new Set(hidden || []);
    return items.filter((item) => !off.has(item.type));
  }

  /**
   * Sections to draw, in registry order: `by` = 'type' → one per type with
   * items (or every visible type when `showEmpty`); 'group' → one per family;
   * anything else → a single untitled section.
   * @returns {{id: string, label: string, icon: string, items: object[]}[]}
   */
  function sections(items, { by = 'type', showEmpty = false, hidden = [] } = {}) {
    const off = new Set(hidden || []);
    if (by === 'type') {
      return TYPES.filter((t) => !off.has(t.id))
        .map((t) => ({ id: t.id, label: t.label, icon: t.icon, items: items.filter((i) => i.type === t.id) }))
        .filter((s) => showEmpty || s.items.length);
    }
    if (by === 'group') {
      const groups = [...new Set(TYPES.map((t) => t.group))];
      return groups
        .map((g) => ({ id: g, label: g[0].toUpperCase() + g.slice(1), icon: '', items: items.filter((i) => BY_ID[i.type] && BY_ID[i.type].group === g) }))
        .filter((s) => showEmpty || s.items.length);
    }
    return [{ id: 'all', label: '', icon: '', items }];
  }

  return { TYPES, BY_ID, typeOf, buildMapItems, countByType, visible, sections };
});
