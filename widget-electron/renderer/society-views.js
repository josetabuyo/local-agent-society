'use strict';

/**
 * DOM views over LasSociety items (society-model.js). Each view only draws
 * and reports back — the meaning of an action belongs to the caller:
 *
 *   handlers.onAction(item, actionId, buttonEl)   mic / exit / unlink
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

  /** One button per action (mic, exit), disabled when it can't run for this item. */
  function actionButtons(item, handlers, className) {
    return M.ACTIONS.map((action) => {
      const d = M.describeAction(item, action);
      const b = el('button', className, M.ACTION_ICONS[action]);
      b.type = 'button';
      b.title = d.title;
      b.disabled = !d.enabled;
      b.dataset.action = action;
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        handlers.onAction(item, action, b);
      });
      b.addEventListener('dblclick', (e) => e.stopPropagation());
      return b;
    });
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

  /** Panel tab: a mini sticky — the same face as a widget, in a square. */
  function tile(item, pos, handlers) {
    const t = el('div', `society-tile kind-${item.kind}${item.isDefault ? ' is-default' : ''}${item.widgetClosed ? ' widget-closed' : ''}`);
    t.dataset.key = item.key;
    const { background, color } = M.chipColors(item.color, 0.78);
    t.style.background = background;
    t.style.color = color;
    t.style.left = `${pos.x}px`;
    t.style.top = `${pos.y}px`;
    t.style.width = t.style.height = `${M.TILE}px`;
    t.title = `${item.label} — ${item.detail}\nDouble-click for actions, drag to move`;
    t.append(el('div', 'tile-icon', M.KIND_ICONS[item.kind] || ''), el('div', 'tile-label', item.label), el('div', 'tile-detail', item.detail));
    const menu = el('div', 'tile-menu');
    menu.append(...actionButtons(item, handlers, 'tile-action'));
    t.appendChild(menu);
    t.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      const open = !t.classList.contains('menu-open');
      t.parentElement.querySelectorAll('.society-tile.menu-open').forEach((o) => o.classList.remove('menu-open'));
      t.classList.toggle('menu-open', open);
    });
    makeDraggable(t, handlers);
    return t;
  }

  const DRAG_THRESHOLD_PX = 3;

  function makeDraggable(t, handlers) {
    t.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.closest('.tile-menu')) return;
      const area = t.parentElement;
      const start = { x: e.clientX, y: e.clientY, left: t.offsetLeft, top: t.offsetTop };
      let dragging = false;
      const move = (ev) => {
        const dx = ev.clientX - start.x;
        const dy = ev.clientY - start.y;
        if (!dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
        dragging = true;
        t.classList.add('dragging');
        const p = M.clamp({ x: start.left + dx, y: start.top + dy }, area.clientWidth, area.clientHeight);
        t.style.left = `${p.x}px`;
        t.style.top = `${p.y}px`;
      };
      const up = () => {
        t.removeEventListener('pointermove', move);
        t.removeEventListener('pointerup', up);
        t.removeEventListener('pointercancel', up);
        if (!dragging) return;
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

  /** Panel tab: every item as a draggable mini sticky, at its saved (or a free) spot. */
  function renderPanel(container, items, saved, handlers) {
    container.innerHTML = '';
    const area = el('div', 'society-panel');
    container.appendChild(area);
    const width = area.clientWidth || container.clientWidth || 260;
    const positions = M.layout(items, saved, width, PANEL_MIN_HEIGHT);
    area.style.height = `${M.panelHeight(positions, PANEL_MIN_HEIGHT)}px`;
    for (const item of items) area.appendChild(tile(item, positions[item.key], handlers));
    area.addEventListener('click', (e) => {
      if (e.target === area) area.querySelectorAll('.society-tile.menu-open').forEach((o) => o.classList.remove('menu-open'));
    });
    if (!items.length) area.appendChild(el('div', 'society-empty', 'Nothing here yet — open a session, or link a friend in the List tab.'));
    return area;
  }

  root.LasSocietyViews = { chip, listRow, renderPanel };
})(self);
