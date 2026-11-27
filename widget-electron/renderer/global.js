'use strict';

/**
 * The global panel (`las map global`): every agent of this Mac on one board,
 * the same mini widgets as an agent's map — parents before their subordinates,
 * and an agent shown nowhere else (off the main screen, nobody's friend)
 * flagged ⚠ so it can be put in order. Its ✕ asks what to do: close its
 * widget, archive it, delete it (society-views.js closeAgentTile).
 *
 * Archive lists the society's archived agents (↩ back, ✕ delete). ⚙ holds the
 * settings shared by every widget — each widget's own ⚙ only links here.
 */
(function () {
  const S = window.LasSociety;
  const V = window.LasSocietyViews;
  const REFRESH_MS = 5000;
  const VIEW_KEY = 'las-map-view:__global__';
  const POS_KEY = 'las-map-positions:__global__';

  const $ = (id) => document.getElementById(id);
  const el = (tag, className, text) => {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  };

  function applyColor() {
    const root = document.documentElement.style;
    root.setProperty('--widget-bg', 'rgba(143, 155, 176, 0.82)');
    root.setProperty('--text-fill', '#000');
    root.setProperty('--btn-fill', 'rgba(0, 0, 0, 0.13)');
    root.setProperty('--map-text', 'rgba(20, 20, 20, 0.92)');
    root.setProperty('--map-tint', 'rgba(0, 0, 0, 0.07)');
    root.setProperty('--map-border', 'rgba(0, 0, 0, 0.25)');
  }

  const store = {
    get(key, fallback) {
      try { return { ...fallback, ...JSON.parse(localStorage.getItem(key) || '{}') }; } catch { return { ...fallback }; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private storage: memory only */ }
    },
  };
  const view = store.get(VIEW_KEY, { layout: 'canvas' });
  const positions = store.get(POS_KEY, {});
  let tree = null;
  let items = [];

  // ── data ────────────────────────────────────────────────────────────────
  async function refresh() {
    const next = await window.las.getSocietyTree().catch(() => null);
    if (!next) {
      $('summary').textContent = 'backend not reachable';
      return;
    }
    const nextItems = S.buildGlobalItems(next);
    const muted = Object.fromEntries(await Promise.all(nextItems.map(async (i) => {
      try { return [i.agent, !!((await window.las.getPrefs(i.agent)) || {}).mute]; } catch { return [i.agent, false]; }
    })));
    for (const i of nextItems) i.muted = muted[i.agent] === true;
    const changed = JSON.stringify(next) !== JSON.stringify(tree) || JSON.stringify(nextItems) !== JSON.stringify(items);
    tree = next;
    items = nextItems;
    const hidden = items.filter((i) => i.hidden).length;
    $('summary').textContent = `${items.length} on ${tree.env || 'this Mac'}${hidden ? ` · ⚠ ${hidden} shown nowhere` : ''} · ${tree.archived.length} archived`;
    if (changed) render();
  }

  // ── actions ─────────────────────────────────────────────────────────────
  async function onClose(item) {
    await V.closeAgentTile(item, null);
    refresh();
  }

  async function onAction(item, action, button, event) {
    if (action === 'exit') return onClose(item);
    if (action === 'map') return window.las.openMap(item.agent);
    if (action === 'open') return window.las.openAgent(item.agent, event && event.type === 'contextmenu' ? 'folder' : 'terminal');
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
    if (action === 'archive') {
      V.closeTilePopup();
      await window.las.archiveAgent(item.agent);
      return refresh();
    }
    return undefined;
  }

  const handlers = {
    onAction,
    onClose,
    closeTitle: (item) => `Close ${item.agent}'s widget, archive it or delete it…`,
    onMove(key, pos) {
      positions[key] = pos;
      store.set(POS_KEY, positions);
    },
  };

  // ── the archive: agents taken out of the society ────────────────────────
  function archiveRow(a) {
    const row = el('div', 'open-row society-row archive-row');
    const label = el('span', 'open-label society-label');
    label.append(el('span', 'archive-name', a.name), el('span', 'society-detail', a.short_description || a.path || ''));
    row.appendChild(label);
    const back = el('button', 'open-move', '↩');
    back.type = 'button';
    back.title = `Bring ${a.name} back to the society (its widget reopens)`;
    back.addEventListener('click', async () => {
      await window.las.unarchiveAgent(a.name);
      refresh();
    });
    const del = el('button', 'open-move', '✕');
    del.type = 'button';
    del.title = `Delete ${a.name} — unregistered from LAS; its folder and files stay`;
    del.addEventListener('click', () => V.guarded('safe', `Delete ${a.name}? It is unregistered from LAS on this Mac. Its folder, files and repo are not touched; a session opened there registers it again.`, async () => {
      await window.las.deleteAgent(a.name);
      refresh();
    }));
    row.append(back, del);
    return row;
  }

  // ── drawing ─────────────────────────────────────────────────────────────
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
      const shelf = (tree && tree.archived) || [];
      for (const a of shelf) box.append(archiveRow(a));
      if (!shelf.length) box.append(el('div', 'society-empty map-list-empty', 'No archived agents — 🗄 on an agent puts it here'));
      return;
    }
    const empty = tree ? 'No agents registered on this Mac' : 'Loading…';
    if (view.layout === 'list') {
      for (const item of items) box.append(V.listRow(item, handlers));
      if (!items.length) box.append(el('div', 'society-empty map-list-empty', empty));
    } else {
      V.renderPanel(box, items, positions, handlers, { empty });
    }
    for (const item of items.filter((i) => i.hidden)) {
      const node = [...host.querySelectorAll('[data-key]')].find((n) => n.dataset.key === item.key);
      if (node) node.classList.add('agent-hidden');
    }
  }

  $('layoutSeg').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    view.archive = b.dataset.value === 'archive';
    if (!view.archive) view.layout = b.dataset.value;
    store.set(VIEW_KEY, view);
    render();
  });
  $('closeBtn').addEventListener('click', () => window.close());

  // ── ⚙: the settings every widget shares (main.js tile reconciler, updates, phones) ──
  const shrinkEl = $('tileShrinkMs');
  const tickEl = $('tileTickMs');
  function applyTileSettings(s) {
    if (!s) return;
    shrinkEl.value = String(s.collapseSettleMs);
    tickEl.value = String(s.tickMs);
  }
  async function initSettings() {
    try {
      const s = await window.las.getTileSettings();
      if (s && s.limits) {
        [shrinkEl.min, shrinkEl.max] = s.limits.collapseSettleMs.map(String);
        [tickEl.min, tickEl.max] = s.limits.tickMs.map(String);
        shrinkEl.placeholder = String(s.defaults.collapseSettleMs);
        tickEl.placeholder = String(s.defaults.tickMs);
      }
      applyTileSettings(s);
    } catch (err) {
      console.warn('[global] could not read tile settings:', err);
    }
  }
  shrinkEl.addEventListener('change', async () => applyTileSettings(await window.las.setTileSettings({ collapseSettleMs: shrinkEl.value })));
  tickEl.addEventListener('change', async () => applyTileSettings(await window.las.setTileSettings({ tickMs: tickEl.value })));
  window.las.onTileSettings(applyTileSettings);

  // Glass look (main.js "glass look"): one switch for every window; macOS only.
  const glassEl = $('glassLook');
  const applyGlass = (g) => {
    if (!g) return;
    glassEl.checked = !!g.on;
    $('glassRow').classList.toggle('hidden', !g.supported);
    glassEl.title = g.native ? 'Liquid Glass (this macOS has it)' : 'Blur behind the widgets (this macOS has no Liquid Glass)';
  };
  window.las.getGlass().then(applyGlass).catch((err) => console.warn('[global] could not read glass setting:', err));
  glassEl.addEventListener('change', async () => applyGlass(await window.las.setGlass(glassEl.checked)));
  window.las.onGlass((flag) => { glassEl.checked = flag !== '0'; const c = document.documentElement.classList; c.toggle('glass', flag !== '0'); c.toggle('native', flag === '2'); });

  const checkEl = $('updateCheck');
  const checkedEl = $('updateChecked');
  function applyUpdateStatus(status) {
    const available = !!(status && status.available);
    const when = status && status.checked_at ? status.checked_at.slice(11, 16) : null;
    checkedEl.textContent = !status ? 'Updates'
      : status.error ? 'Updates · check failed'
      : available ? `Update available (${status.behind} new) · ${when}` : `Up to date · ${when}`;
    $('settingsBtn').classList.toggle('has-update', available);
  }
  checkEl.addEventListener('click', async () => {
    checkEl.disabled = true;
    checkEl.textContent = 'Checking…';
    try {
      applyUpdateStatus(await window.las.checkUpdate());
    } finally {
      checkEl.disabled = false;
      checkEl.textContent = 'Check now';
    }
  });
  window.las.onUpdateStatus(applyUpdateStatus);
  window.las.getUpdateStatus().then(applyUpdateStatus).catch(() => {});
  $('pairingOpen').addEventListener('click', () => window.las.openPairing());

  $('settingsBtn').addEventListener('click', () => {
    const open = $('globalSettings').classList.toggle('hidden') === false;
    $('settingsBtn').classList.toggle('active', open);
    if (open) initSettings();
  });

  // ── start ───────────────────────────────────────────────────────────────
  applyColor();
  render();
  refresh();
  setInterval(refresh, REFRESH_MS);
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 120);
  });
})();
