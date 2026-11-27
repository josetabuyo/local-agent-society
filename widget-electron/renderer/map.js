'use strict';

/**
 * The map window (docs/adr/0007) — the society panel's 2D board in a widget
 * of its own: the agent's color glass, the same mini widgets, draggable, one
 * board (no grouping), and the same button bar on double-click or hold
 * (🚪 ⚙ ⧉ 🔊 ⌨ 🎤 ⌖ 📄, per kind — society-model.js ACTIONS_BY_KIND). 🎤 and ⌨
 * run on the agent's own widget, which owns the recorder and the keyboard.
 * Every tile also has a ✕: a terminal or command closes, a repo or URL leaves
 * the map — straight away in dangerous mode, after a popup in safe mode
 * (security_mode, `las agent security`). A friend's ✕ always asks what to do:
 * close its widget, archive it here, unfriend it (to the society's archive
 * too when it would show nowhere else), or delete it (society-views.js
 * closeAgentTile). Elements are added
 * with `las map add`. Canvas/List is the only display choice; Archive, next to
 * them, lists what this agent put away (the society's archived agents live
 * in ⚙ → All widgets).
 *
 * The 🎤 badge sits on the corner of the mini widget the agent's mic talks to
 * (its `sessions.target`, or `sessions.mic_to` when it is a friend). Drag it
 * onto any other mini widget that can take a dictation — a terminal, a
 * command, a friend — to move the mic there. There is always exactly one
 * holder (every session when it talks to all): the target, else the
 * last-used session, else the first tile that can take it.
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
  // Where the mic is: {target, mic_to} from the agent's sessions view.
  let mic = { target: 'default', mic_to: '' };

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
    const nextMic = sessions && typeof sessions.target === 'string'
      ? { target: sessions.target, mic_to: sessions.mic_to || '' } : mic;
    // Redraw only when something changed: a redraw mid-drag would drop the tile.
    if (JSON.stringify(next) === JSON.stringify(items) && JSON.stringify(nextMic) === JSON.stringify(mic)) return;
    items = next;
    mic = nextMic;
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
    if (item.kind === 'friend') return `Close ${item.agent}'s widget, archive it, unfriend it or delete it…`;
    if (item.kind === 'repo' || item.kind === 'url') return 'Take it off the map';
    return item.kind === 'command' ? 'Stop this command' : 'Close this terminal';
  }

  async function onClose(item) {
    if (item.kind === 'friend') {
      // A choice, not a confirmation: the popup asks whatever the security mode.
      await V.closeAgentTile(item, agentName);
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
    if (action === 'archive') {
      // Not destructive — it stays in the archive, one click from coming back.
      V.closeTilePopup();
      await window.las.archiveEntry(agentName, item.kind === 'friend' ? `friend:${item.agent}` : item.elementId);
      return refresh();
    }
    return undefined;
  }

  // ── the archive: what this agent put away (🗄 in the tools pill) ────────────
  let archive = [];
  let archivedAgents = [];

  /** This agent's own archive only — archived agents (the society's) are in ⚙ → All widgets. */
  async function refreshArchive() {
    const res = await window.las.getArchive(agentName).catch(() => null);
    const next = (res && res.archive) || [];
    if (JSON.stringify(next) === JSON.stringify(archive)) return false;
    archive = next;
    return true;
  }

  function archiveDetail(entry) {
    if (entry.type === 'friend') return entry.registered ? 'friend' : 'friend · not registered';
    if (entry.type === 'repo') return entry.github || entry.abs_path || 'repo';
    return entry.url || 'url';
  }

  function archiveRow(entry) {
    const row = el('div', 'open-row society-row archive-row');
    const label = el('span', 'open-label society-label');
    const icon = { friend: '\u{1F464}', repo: '\u{1F4C1}', url: '\u{1F517}' }[entry.type] || '•';
    label.append(el('span', 'archive-name', `${icon} ${entry.label}`), el('span', 'society-detail', archiveDetail(entry)));
    row.appendChild(label);
    const restore = el('button', 'open-move', '↩');
    restore.type = 'button';
    restore.title = entry.type === 'friend' ? `Bring ${entry.label} back among the friends` : 'Put it back on the map';
    restore.addEventListener('click', async () => {
      await window.las.restoreArchiveEntry(agentName, entry.id);
      await refreshArchive();
      render();
      refresh();
    });
    const forget = el('button', 'open-move', '✕');
    forget.type = 'button';
    forget.title = 'Forget it for good';
    // Permanent: always asks, whatever the security mode.
    const question = entry.type === 'friend'
      ? `Forget ${entry.label} for good? It is only unlinked from ${agentName} — the agent itself, its folder and its repo stay.`
      : `Forget “${entry.label}” for good? It leaves the archive and cannot come back from here — the folder or the page itself is not touched.`;
    forget.addEventListener('click', () => V.guarded('safe', question, async () => {
      await window.las.forgetArchiveEntry(agentName, entry.id);
      await refreshArchive();
      render();
    }));
    row.append(restore, forget);
    return row;
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
    host.className = `map-body layout-${view.archive ? 'list' : view.layout}`;
    const box = el('div', 'map-board');
    host.append(box);
    for (const b of $('layoutSeg').querySelectorAll('button')) {
      b.classList.toggle('active', view.archive ? b.dataset.value === 'archive' : b.dataset.value === view.layout);
    }
    if (view.archive) {
      placeMic();
      // The archive is a list, for now: what was put away, ↩ back, ✕ for good.
      for (const entry of archive) box.append(archiveRow(entry));
      if (!archive.length) box.append(el('div', 'society-empty map-list-empty', 'The archive is empty — 🗄 on a friend, repo or link puts it here'));
      return;
    }
    const empty = 'Nothing on this map yet — las map add repo PATH · las map add url URL';
    if (view.layout === 'list') {
      for (const item of items) box.append(listRow(item));
      if (!items.length) box.append(el('div', 'society-empty map-list-empty', empty));
    } else {
      V.renderPanel(box, items, positions, handlers, { empty });
    }
    placeMic();
  }

  // ── the mic: a 🎤 badge on the mini widget it talks to, dragged to move it ──
  const MIC_TAKERS = new Set(['terminal', 'command', 'friend']);

  /** Can the mic be dropped on this item? A session, or a friend that can be reached. */
  function takesMic(item) {
    return !!item && MIC_TAKERS.has(item.kind) && !(item.kind === 'friend' && item.registered === false);
  }

  /** The keys of the tiles that hold the mic now (several when it talks to all sessions). */
  function micKeys() {
    if (mic.mic_to) return items.filter((i) => i.kind === 'friend' && i.agent === mic.mic_to).map((i) => i.key);
    const sessions = items.filter((i) => i.kind === 'terminal' || i.kind === 'command');
    if (mic.target === 'all') return sessions.map((i) => i.key);
    // Sessions come most-recently-used first: a runtime name means the first of that runtime.
    const picked = mic.target === 'default' ? null
      : sessions.find((i) => i.sid === mic.target) || sessions.find((i) => i.runtime === mic.target);
    // Not connected (or default): the backend falls back to the last-used session;
    // none marked: the first tile that can take the mic, so it is always somewhere.
    const holder = picked || sessions.find((i) => i.isDefault) || items.find(takesMic);
    return holder ? [holder.key] : [];
  }

  function micWhere() {
    if (mic.mic_to) return `${mic.mic_to} (its own target picks the terminal)`;
    if (mic.target === 'default') return `${agentName}'s last-used session`;
    if (mic.target === 'all') return `every session of ${agentName}`;
    return `${agentName} · ${mic.target}`;
  }

  /** Put the 🎤 badge on its tile(s) (or row(s)). */
  function placeMic() {
    const host = $('map');
    for (const old of host.querySelectorAll('.mic-badge')) old.remove();
    const keys = view.archive ? [] : micKeys();
    for (const key of keys) {
      const target = [...host.querySelectorAll('[data-key]')].find((e) => e.dataset.key === key);
      if (!target) continue;
      const badge = el('span', 'mic-badge', '🎤');
      startMicDrag(badge);
      badge.title = `The mic talks to ${micWhere()} — drag it onto another terminal, command or friend to move it`;
      target.appendChild(badge);
    }
  }

  async function moveMic(patch) {
    const res = await window.las.setSessionsConfig(agentName, patch);
    if (res && res.sessions) mic = { target: res.sessions.target, mic_to: res.sessions.mic_to || '' };
    render();
  }

  /** The mic dropped on `item`: a friend → that friend; a session → this agent, that session. */
  function dropMicOn(item) {
    if (item.kind === 'friend') return moveMic({ mic_to: item.agent });
    // One session of its runtime: aim at the runtime (survives that terminal reopening); several: that very one.
    const sameRuntime = items.filter((i) => (i.kind === 'terminal' || i.kind === 'command') && i.runtime === item.runtime);
    return moveMic({ target: sameRuntime.length === 1 ? item.runtime : item.sid, mic_to: '' });
  }

  function itemAt(x, y) {
    const hit = document.elementFromPoint(x, y);
    const host = hit && hit.closest('#map [data-key]');
    return host ? items.find((i) => i.key === host.dataset.key) || null : null;
  }

  /** Press on a tile's 🎤 badge and drag it: it follows the pointer, a tile that takes it lights up. */
  function startMicDrag(source) {
    source.addEventListener('dblclick', (e) => e.stopPropagation());
    source.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.stopPropagation();
      e.preventDefault();
      const start = { x: e.clientX, y: e.clientY };
      let ghost = null;
      let lit = null;
      const light = (node) => {
        if (lit === node) return;
        if (lit) lit.classList.remove('mic-drop-ok');
        lit = node;
        if (lit) lit.classList.add('mic-drop-ok');
      };
      const move = (ev) => {
        if (!ghost) {
          if (Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 3) return;
          ghost = el('div', 'mic-ghost', '🎤');
          document.body.appendChild(ghost);
          source.classList.add('mic-lifted');
        }
        ghost.style.left = `${ev.clientX}px`;
        ghost.style.top = `${ev.clientY}px`;
        ghost.style.display = 'none';
        const item = itemAt(ev.clientX, ev.clientY);
        ghost.style.display = '';
        const node = item && takesMic(item) ? [...$('map').querySelectorAll('[data-key]')].find((n) => n.dataset.key === item.key) : null;
        light(node || null);
      };
      const up = (ev) => {
        document.removeEventListener('pointermove', move, true);
        document.removeEventListener('pointerup', up, true);
        light(null);
        source.classList.remove('mic-lifted');
        if (!ghost) return;
        ghost.remove();
        const item = itemAt(ev.clientX, ev.clientY);
        if (takesMic(item)) dropMicOn(item);
      };
      document.addEventListener('pointermove', move, true);
      document.addEventListener('pointerup', up, true);
    });
  }


  $('layoutSeg').addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    view.archive = b.dataset.value === 'archive';
    if (!view.archive) view.layout = b.dataset.value;
    saveView();
    if (view.archive) await refreshArchive();
    render();
  });
  $('closeBtn').addEventListener('click', () => window.close());

  /**
   * 🙏 — ask every Claude/Codex session what it is working on (backend
   * request_session_titles; a shell cannot describe itself). Each one answers
   * with `las agent title`, asynchronously: re-read a few times so the new
   * descriptions land on the tiles without waiting for the 5 s refresh.
   */
  async function askDescriptions() {
    const btn = $('describeBtn');
    if (btn.classList.contains('asking')) return;
    btn.classList.add('asking');
    const res = await window.las.requestSessionTitles(agentName).catch(() => null);
    if (!res || !Array.isArray(res.asked)) {
      btn.title = 'Could not ask the terminals — is the backend up?';
      btn.classList.remove('asking');
      return;
    }
    btn.title = res.asked.length
      ? `Asked ${res.asked.length} terminal${res.asked.length === 1 ? '' : 's'} — their descriptions arrive in a few seconds`
      : 'No terminal here can describe itself (a shell cannot)';
    for (const delay of [3000, 5000, 7000, 15000]) {
      await new Promise((resolve) => setTimeout(resolve, delay));
      await refresh();
    }
    btn.classList.remove('asking');
  }
  $('describeBtn').addEventListener('click', askDescriptions);

  // ── start ───────────────────────────────────────────────────────────────
  document.title = `Map — ${agentName}`;
  $('agentName').textContent = agentName;
  applyColor();
  render();
  refresh();
  if (view.archive) refreshArchive().then(render);
  setInterval(async () => {
    await refresh();
    if (view.archive && (await refreshArchive())) render();
  }, REFRESH_MS);
  // The board is laid out for the window's width: follow a resize.
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 120);
  });
})();

// Glass look toggled from the global map's ⚙ (main.js 'glass:changed').
window.las.onGlass((flag) => { const c = document.documentElement.classList; c.toggle('glass', flag !== '0'); c.toggle('native', flag === '2'); });
