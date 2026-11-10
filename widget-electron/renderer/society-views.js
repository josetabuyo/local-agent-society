'use strict';

/**
 * DOM views over LasSociety items (society-model.js). Each view only draws
 * and reports back — the meaning of an action belongs to the caller:
 *
 *   handlers.onAction(item, actionId, buttonEl, event)   any of M.actionsFor(item), or unlink
 *   handlers.onMove(key, {x, y})                  panel only: a tile was dropped
 *
 * Two views today: a row (List tab) and a draggable mini-sticky board
 * (Panel tab). A future view (a whole-screen 2D board) reuses the same
 * items, the same handlers and the same tile/chip builders.
 */
(function (root) {
  const M = root.LasSociety;

  function el(tag, className, text) {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  /** The agent-colored chip: the item's name inside a pill of its agent's color. */
  function chip(item) {
    const c = el('span', `society-chip kind-${item.kind}`, item.label);
    const { background, color } = M.chipColors(item.color);
    c.style.background = background;
    c.style.color = color;
    c.title = `${item.label} — ${item.detail}`;
    return c;
  }

  /** One button per action of this item (its whole button bar), disabled when it can't run. */
  function actionButtons(item, handlers, className) {
    return M.actionsFor(item).map((action) => {
      const d = M.describeAction(item, action);
      const b = el('button', className, M.actionIcon(item, action));
      b.type = 'button';
      b.title = d.title;
      b.disabled = !d.enabled;
      b.dataset.action = action;
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        handlers.onAction(item, action, b, e);
      });
      b.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!b.disabled) handlers.onAction(item, action, b, e);
      });
      b.addEventListener('dblclick', (e) => e.stopPropagation());
      return b;
    });
  }

  // ── the tile popup: a floating button bar above the tile ─────────────────
  // Not inside the tile's square: it hangs over the tile (below it when
  // there's no room above), positioned against the window so neither the
  // panel nor the drawer can clip it. One open at a time.

  let popup = null;

  function closeTilePopup() {
    if (!popup) return;
    popup.tile.classList.remove('menu-open');
    popup.bar.remove();
    document.removeEventListener('pointerdown', popup.outside, true);
    popup = null;
  }

  function placePopup(bar, tileEl) {
    const r = tileEl.getBoundingClientRect();
    const w = bar.offsetWidth;
    const h = bar.offsetHeight;
    const margin = 4;
    const left = Math.max(margin, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - margin));
    const above = r.top - h - margin;
    const top = above >= margin ? above : Math.min(r.bottom + margin, window.innerHeight - h - margin);
    bar.style.left = `${Math.round(left)}px`;
    bar.style.top = `${Math.round(top)}px`;
    bar.classList.toggle('below', above < margin);
  }

  function openTilePopup(tileEl, item, handlers) {
    closeTilePopup();
    const bar = el('div', 'tile-popup');
    bar.dataset.key = item.key;
    const { background, color } = M.chipColors(item.color, 0.95);
    bar.style.background = background;
    bar.style.color = color;
    bar.append(...actionButtons(item, handlers, 'tile-action'));
    document.body.appendChild(bar);
    placePopup(bar, tileEl);
    tileEl.classList.add('menu-open');
    const outside = (e) => {
      if (bar.contains(e.target) || tileEl.contains(e.target)) return;
      closeTilePopup();
    };
    document.addEventListener('pointerdown', outside, true);
    popup = { bar, tile: tileEl, outside };
  }

  /** List tab: one row per item — chip, detail, actions (+ unlink for a friend). */
  function listRow(item, handlers) {
    const row = el('div', 'open-row society-row');
    row.dataset.key = item.key;
    const label = el('span', 'open-label society-label');
    label.append(chip(item), el('span', 'society-detail', item.detail));
    row.appendChild(label);
    row.append(...actionButtons(item, handlers, 'open-move'));
    if (item.kind === 'friend') {
      const unlink = el('button', 'open-move', '✕');
      unlink.type = 'button';
      unlink.title = `Unlink ${item.agent} (only from this agent's friends)`;
      unlink.dataset.action = 'unlink';
      unlink.addEventListener('click', () => handlers.onAction(item, 'unlink', unlink));
      row.appendChild(unlink);
    }
    return row;
  }

  /**
   * The mini widget — THE reusable face of anything in the society, at the
   * smallest size a widget can have: a panel tile (friends, sessions) and a
   * widget shrunk to icon size both draw this. An agent (friend, or a widget
   * itself) is only its name; a session has its icon top-left with its
   * runtime next to it, and its title or command below.
   * @param {object} item  a LasSociety item (buildItems / agentItem)
   * @param {{alpha?: number, className?: string}} [opts]
   */
  function miniWidget(item, { alpha = 0.78, className = '' } = {}) {
    const w = el('div', `mini-widget kind-${item.kind}${className ? ` ${className}` : ''}`);
    const { background, color } = M.chipColors(item.color, alpha);
    w.style.background = background;
    w.style.color = color;
    if (item.kind === 'terminal' || item.kind === 'command' || item.kind === 'repo' || item.kind === 'url') {
      const head = el('div', 'mw-head');
      head.append(el('span', 'mw-icon', item.icon || M.KIND_ICONS[item.kind] || ''), el('span', 'mw-runtime', item.label));
      w.append(head, el('div', 'mw-detail', item.detail));
    } else {
      w.appendChild(el('div', 'mw-name', item.label));
    }
    return w;
  }

  /**
   * Panel tab: a mini widget placed on the board — draggable, with its button bar on double-click or hold.
   * `readOnly` (the map window): no button bar; a click opens the item's `href`, if any, via handlers.onOpen,
   * handlers.onClose, when given (the map), adds a ✕ in the tile's corner, in either mode.
   */
  function tile(item, pos, handlers, readOnly = false) {
    const t = miniWidget(item, { className: `society-tile${item.isDefault ? ' is-default' : ''}${item.widgetClosed ? ' widget-closed' : ''}` });
    t.dataset.key = item.key;
    t.style.left = `${pos.x}px`;
    t.style.top = `${pos.y}px`;
    t.style.width = t.style.height = `${M.TILE}px`;
    if (handlers.onClose) {
      // The map's ✕ in the corner (closes a terminal or a friend's widget, takes a repo/url off the map).
      const close = el('button', 'mw-close', '✕');
      close.type = 'button';
      close.title = handlers.closeTitle ? handlers.closeTitle(item) : 'Close';
      close.addEventListener('pointerdown', (e) => e.stopPropagation());
      close.addEventListener('dblclick', (e) => e.stopPropagation());
      close.addEventListener('click', (e) => {
        e.stopPropagation();
        handlers.onClose(item, close);
      });
      t.appendChild(close);
    }
    if (readOnly) {
      t.title = `${item.label}${item.detail ? ` — ${item.detail}` : ''}${item.href ? `\nClick: open ${item.href}` : ''}\nDrag to move`;
      if (item.href) t.classList.add('has-href');
      makeDraggable(t, item, handlers, true);
      return t;
    }
    t.title = `${item.label}${item.detail ? ` — ${item.detail}` : ''}\nDouble-click or hold for actions, drag to move`;
    t.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      if (popup && popup.tile === t) closeTilePopup();
      else openTilePopup(t, item, handlers);
    });
    makeDraggable(t, item, handlers);
    return t;
  }

  const DRAG_THRESHOLD_PX = 3;
  // Same hold as the face's ⧉ and 👥 buttons (widget.js OPEN_LONG_PRESS_MS).
  const LONG_PRESS_MS = 600;

  /** Drag to move; hold still for LONG_PRESS_MS to open the tile's button bar. */
  function makeDraggable(t, item, handlers, readOnly = false) {
    t.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      const area = t.parentElement;
      const start = { x: e.clientX, y: e.clientY, left: t.offsetLeft, top: t.offsetTop };
      let dragging = false;
      // The map (readOnly) has no button bar: no hold timer at all.
      let hold = null;
      if (!readOnly) hold = setTimeout(() => {
        hold = null;
        if (!dragging && !(popup && popup.tile === t)) openTilePopup(t, item, handlers);
      }, LONG_PRESS_MS);
      const cancelHold = () => { if (hold) clearTimeout(hold); hold = null; };
      const move = (ev) => {
        const dx = ev.clientX - start.x;
        const dy = ev.clientY - start.y;
        if (!dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
        cancelHold();
        dragging = true;
        t.classList.add('dragging');
        if (popup && popup.tile === t) closeTilePopup();
        const p = M.clamp({ x: start.left + dx, y: start.top + dy }, area.clientWidth, area.clientHeight);
        t.style.left = `${p.x}px`;
        t.style.top = `${p.y}px`;
      };
      const up = () => {
        cancelHold();
        t.removeEventListener('pointermove', move);
        t.removeEventListener('pointerup', up);
        t.removeEventListener('pointercancel', up);
        if (!dragging) {
          if (readOnly && item.href && handlers.onOpen) handlers.onOpen(item);
          return;
        }
        t.classList.remove('dragging');
        handlers.onMove(t.dataset.key, { x: t.offsetLeft, y: t.offsetTop });
      };
      t.setPointerCapture(e.pointerId);
      t.addEventListener('pointermove', move);
      t.addEventListener('pointerup', up);
      t.addEventListener('pointercancel', up);
    });
  }

  const PANEL_MIN_HEIGHT = 2 * M.TILE + M.GAP;

  /**
   * Panel tab: every item as a draggable mini sticky, at its saved (or a free) spot.
   * `opts.readOnly`: the map window — tiles drag and open their link, never show a button bar.
   * `opts.empty`: the text shown when there is nothing to draw.
   */
  function renderPanel(container, items, saved, handlers, opts = {}) {
    // Redrawn (a mute toggled, a session came or went): keep the popup on the same item.
    const reopenKey = popup && popup.bar.dataset.key;
    closeTilePopup();
    container.innerHTML = '';
    const area = el('div', 'society-panel');
    container.appendChild(area);
    const width = area.clientWidth || container.clientWidth || 260;
    // A drawer the user sized gives the body a real height: the board fills it.
    const room = Math.max(PANEL_MIN_HEIGHT, container.clientHeight);
    const positions = M.layout(items, saved, width, room);
    area.style.height = `${M.panelHeight(positions, room)}px`;
    for (const item of items) area.appendChild(tile(item, positions[item.key], handlers, !!opts.readOnly));
    const again = reopenKey && items.find((i) => i.key === reopenKey);
    const againEl = again && [...area.children].find((c) => c.dataset.key === reopenKey);
    if (againEl) openTilePopup(againEl, again, handlers);
    if (!items.length) area.appendChild(el('div', 'society-empty', opts.empty || 'Nothing here yet — open a session, or link a friend in the List tab.'));
    return area;
  }

  // ── the security gate (docs/adr/0007 §4): does a destructive action ask? ──
  // `dangerous` (the default, made for voice): it just runs. `safe`: a popup
  // in this window asks first — never a browser alert/confirm, which would
  // freeze the window. One open at a time; Esc or Cancel drops the action.

  let confirmEl = null;

  function closeConfirm() {
    if (!confirmEl) return;
    document.removeEventListener('keydown', confirmEl.onKey, true);
    confirmEl.remove();
    confirmEl = null;
  }

  /** Ask `question` in a popup; resolves true (Accept) or false (Cancel, Esc, a click outside). */
  function confirmPopup(question, { okLabel = 'Accept', cancelLabel = 'Cancel' } = {}) {
    closeConfirm();
    return new Promise((resolve) => {
      const veil = el('div', 'las-confirm-veil');
      const box = el('div', 'las-confirm');
      box.setAttribute('role', 'alertdialog');
      box.append(el('div', 'las-confirm-title', '\u{1F6E1}\uFE0F Safe mode'), el('div', 'las-confirm-text', question));
      const row = el('div', 'las-confirm-buttons');
      const cancel = el('button', 'las-confirm-cancel', cancelLabel);
      const ok = el('button', 'las-confirm-ok', okLabel);
      cancel.type = ok.type = 'button';
      row.append(cancel, ok);
      box.appendChild(row);
      veil.appendChild(box);
      const done = (answer) => { closeConfirm(); resolve(answer); };
      cancel.addEventListener('click', () => done(false));
      ok.addEventListener('click', () => done(true));
      veil.addEventListener('pointerdown', (e) => { if (e.target === veil) done(false); });
      veil.onKey = (e) => {
        if (e.key === 'Escape') { e.preventDefault(); done(false); }
        if (e.key === 'Enter') { e.preventDefault(); done(true); }
      };
      document.addEventListener('keydown', veil.onKey, true);
      confirmEl = veil;
      document.body.appendChild(veil);
      ok.focus();
    });
  }

  /** Run `action` now (dangerous), or only after the popup is accepted (safe). */
  async function guarded(mode, question, action) {
    if (mode === 'safe' && !(await confirmPopup(question))) return undefined;
    return action();
  }

  root.LasSocietyViews = { chip, miniWidget, listRow, renderPanel, closeTilePopup, confirmPopup, guarded };
})(self);
