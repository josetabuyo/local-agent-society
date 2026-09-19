'use strict';

/**
 * Renderer logic for one agent widget window. No Node/Electron APIs here —
 * everything comes through the `window.las` bridge exposed by preload.js.
 */

const agentName = window.las.getAgentName() || 'Agent';

// Paint the real widget color on the very first frame instead of a flash
// of widget.css's placeholder green: main.js already knows this window's
// saved color/opacity synchronously (electron-store) before it even calls
// loadFile, so it passes them in the URL query string alongside `agent` —
// applyColorVars (defined below) is called with them immediately, ahead of
// the async window.las.getPrefs() round-trip in init() that used to be the
// only thing setting these CSS vars.
{
  const initialParams = new URLSearchParams(window.location.search);
  const initialColor = initialParams.get('color');
  const initialOpacity = initialParams.get('opacity');
  if (initialColor && initialOpacity !== null) {
    applyColorVars(initialColor, Number(initialOpacity));
  }
}

const nameEl = document.getElementById('name');
const logEl = document.getElementById('log');
const widgetEl = document.getElementById('widget');
const gearEl = document.getElementById('gear');
const settingsEl = document.getElementById('settings');
const colorEl = document.getElementById('color');
const opacityEl = document.getElementById('opacity');
const alwaysOnTopEl = document.getElementById('alwaysOnTop');
const muteEl = document.getElementById('mute');
const expandWhenHiddenEl = document.getElementById('expandWhenHidden');
const wakeEnabledEl = document.getElementById('wakeEnabled');
const micLanguageEl = document.getElementById('micLanguage');
const doorEl = document.getElementById('door');

document.title = agentName;

// ── name sizing/line-breaking ────────────────────────────────────────────────
// Ported from the retired Swift widget's fitFontSizeAndSplit/smartSplit
// (swift-widget-final tag, widget/tray.swift): shrink the name from a
// starting size until it fits on one line, and if it still doesn't at a
// reasonable size, break it at whichever generic title boundary — a space,
// a hyphen, or a lowercase->Uppercase (camelCase/PascalCase) transition —
// falls closest to the middle, then fit that two-line version instead.
// Applied both to the compact face (name must fully fit the default widget
// width) and the occlusion-expanded banner (name should fill the much
// bigger box), just with different size/box bounds — see fitNameToBox.

const measureCtx = document.createElement('canvas').getContext('2d');

function measureTextWidth(text, sizePx) {
  measureCtx.font = `800 ${sizePx}px -apple-system, "Segoe UI", system-ui, sans-serif`;
  return measureCtx.measureText(text).width;
}

function smartSplit(text) {
  const chars = [...text];
  const mid = chars.length / 2;

  let bestSpaceIdx = -1;
  let bestSpaceDist = Infinity;
  for (let i = 0; i < chars.length; i++) {
    if (chars[i] === ' ' || chars[i] === '-') {
      const dist = Math.abs(i - mid);
      if (dist < bestSpaceDist) { bestSpaceDist = dist; bestSpaceIdx = i; }
    }
  }
  if (bestSpaceIdx !== -1) {
    const before = chars.slice(0, bestSpaceIdx).join('').trim();
    const after = chars.slice(bestSpaceIdx + 1).join('').trim();
    if (before && after) return `${before}\n${after}`;
  }

  let bestCamelIdx = -1;
  let bestCamelDist = Infinity;
  for (let i = 1; i < chars.length; i++) {
    if (/[A-Z]/.test(chars[i]) && /[a-z]/.test(chars[i - 1])) {
      const dist = Math.abs(i - mid);
      if (dist < bestCamelDist) { bestCamelDist = dist; bestCamelIdx = i; }
    }
  }
  if (bestCamelIdx !== -1) return `${chars.slice(0, bestCamelIdx).join('')}\n${chars.slice(bestCamelIdx).join('')}`;

  return text;
}

function fitFontSizeAndSplit(text, maxWidth, maxHeight, start, min) {
  const effectiveStart = maxHeight ? Math.min(start, Math.floor(maxHeight * 0.9)) : start;

  let size = effectiveStart;
  const singleLineFloor = Math.max(min, Math.floor(effectiveStart * 0.5));
  while (size > singleLineFloor) {
    if (measureTextWidth(text, size) <= maxWidth) return { size, text };
    size -= 1;
  }

  const splitText = smartSplit(text);
  if (splitText !== text) {
    const lines = splitText.split('\n');
    const availH = maxHeight || 96;
    let splitSize = Math.min(effectiveStart, Math.floor(availH / 2.2));
    while (splitSize > min) {
      const maxW = Math.max(...lines.map((l) => measureTextWidth(l, splitSize)));
      if (maxW <= maxWidth) return { size: splitSize, text: splitText };
      splitSize -= 1;
    }
    return { size: min, text: splitText };
  }

  while (size > min) {
    if (measureTextWidth(text, size) <= maxWidth) return { size, text };
    size -= 1;
  }
  return { size: min, text };
}

const COMPACT_START_SIZE = 32;
const COMPACT_MIN_SIZE = 13;
const EXPANDED_MIN_SIZE = 40;

function fitNameToBox() {
  const expanded = widgetEl.classList.contains('occlusion-expanded');
  let maxWidth;
  let maxHeight = null;
  let start;
  let min;
  if (expanded) {
    maxWidth = window.innerWidth * 0.92;
    maxHeight = window.innerHeight * 0.8;
    start = Math.floor(Math.min(window.innerWidth, window.innerHeight) * 0.35);
    min = EXPANDED_MIN_SIZE;
  } else {
    const doorWidth = doorEl.offsetWidth || 26;
    maxWidth = Math.max(40, nameEl.parentElement.clientWidth - doorWidth - 8);
    start = COMPACT_START_SIZE;
    min = COMPACT_MIN_SIZE;
  }
  const { size, text } = fitFontSizeAndSplit(agentName, maxWidth, maxHeight, start, min);
  nameEl.style.fontSize = `${size}px`;
  const isSplit = text.includes('\n');
  nameEl.style.whiteSpace = isSplit ? 'pre-line' : 'nowrap';
  nameEl.style.lineHeight = isSplit ? '1.05' : '';
  nameEl.textContent = text;
  // Occlusion-expanded's banner name is always centered via its own CSS
  // (position untouched by --reveal, see widget.css's .occlusion-expanded
  // .name override) — no need to compute a hover-reveal target for it.
  if (!expanded) updateNameCenterOffset(size, text);
}

fitNameToBox();

// Where the hover-resting name should land: the distance from #name's
// normal (fully revealed) position to the widget's geometric center, plus
// the local x-coordinate the "grow" scale should expand from. Measured off
// the ACTUAL rendered text (via the same canvas metrics fitFontSizeAndSplit
// uses), not #name's flex-stretched box width — the box fills the space
// between the widget's left edge and the door button regardless of how
// short the name is, so centering on the box instead of the glyphs would
// leave the resting title visibly off-center. offsetLeft/offsetTop/
// offsetHeight are layout-only (unaffected by the CSS transform this very
// function feeds), so this stays correct however far along --reveal is.
function updateNameCenterOffset(size, text) {
  const lines = text.split('\n');
  const textWidth = Math.max(...lines.map((l) => measureTextWidth(l, size)));
  const cx = widgetEl.clientWidth / 2 - (nameEl.offsetLeft + textWidth / 2);
  const cy = widgetEl.clientHeight / 2 - (nameEl.offsetTop + nameEl.offsetHeight / 2);
  widgetEl.style.setProperty('--name-cx', `${cx}px`);
  widgetEl.style.setProperty('--name-cy', `${cy}px`);
  widgetEl.style.setProperty('--name-origin-x', `${textWidth / 2}px`);
}

// micLanguage defaults to Spanish, not auto-detect or the agent's TTS
// locale — per explicit request: dictation should assume Spanish unless the
// user picks otherwise, since it's what most agents on this machine are
// dictated to in regardless of what language their own TTS voice speaks.
let prefs = { color: '#90c060', opacity: 0.72, alwaysOnTop: true, mute: false, expandWhenHidden: true, micLanguage: 'es' };
let locale = 'en-US';

/** '#rrggbb' + 0..1 alpha -> 'rgba(r, g, b, a)'. */
function hexToRgba(hex, alpha) {
  const n = parseInt(hex.replace('#', ''), 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** '#rrggbb' + 0..1 alpha, darkened by `amount` (0..1) -> 'rgba(r, g, b, a)'.
 * Used for the local-msg accent tail: a hue tied to the widget's own color
 * (unlike the neutral --bubble-tint), but a shade darker so it reads as an
 * accent on top of the same-hued bubble rather than disappearing into it. */
function darkenHexToRgba(hex, alpha, amount) {
  const n = parseInt(hex.replace('#', ''), 16);
  const r = Math.round(((n >> 16) & 255) * (1 - amount));
  const g = Math.round(((n >> 8) & 255) * (1 - amount));
  const b = Math.round((n & 255) * (1 - amount));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * WCAG relative luminance of a '#rrggbb' color, 0 (black) .. 1 (white).
 * Used to pick dark-on-light vs light-on-dark log/bubble text instead of a
 * fixed color — the widget's background is user-configurable (any hue,
 * light or dark), so a hardcoded text color reads fine against some choices
 * and unreadable against others.
 */
function relativeLuminance(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  const toLinear = (c) => {
    c /= 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const r = toLinear((n >> 16) & 255);
  const g = toLinear((n >> 8) & 255);
  const b = toLinear(n & 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * Sets just the color-derived CSS custom properties on :root — the subset
 * that determines the widget's visible background/text/bubble tint. Split
 * out from applyPrefsToDom so it can also run synchronously at script
 * start (see the top of this file), from color/opacity handed in via the
 * URL query string, before the async window.las.getPrefs() round-trip
 * resolves — otherwise the window briefly paints widget.css's fallback
 * --widget-bg (a placeholder green) and only switches to the real color
 * once that IPC call returns, which reads as a startup flash/glitch.
 *
 * Set on the root, not widgetEl: #settings/#commands/#commandEdit/
 * #ttyPicker are siblings of #widget in the DOM (not descendants), so a
 * CSS custom property set on widgetEl's own inline style wouldn't inherit
 * into them — :root is the shared ancestor all of them do inherit from.
 */
function applyColorVars(color, opacity) {
  // --widget-bg bakes the opacity into the background color's alpha channel
  // instead of the old `opacity` CSS property on .widget: that property faded
  // EVERYTHING including text/buttons, which is why a very transparent widget
  // used to make the agent name unreadable too. Now only fills fade with the
  // opacity slider — the crisp outline (text-stroke on the name, border on
  // the face buttons) stays fully opaque regardless, so both stay legible.
  document.documentElement.style.setProperty('--widget-bg', hexToRgba(color, opacity));
  document.documentElement.style.setProperty('--text-fill', hexToRgba('#141414', opacity));
  document.documentElement.style.setProperty('--btn-fill', `rgba(0, 0, 0, ${(0.16 * opacity).toFixed(3)})`);

  // Log/bubble contrast: dark widget color -> light text on a light-tinted
  // bubble, light widget color -> dark text on a dark-tinted bubble — same
  // two degrees of freedom as the rest of the widget (the chosen color and
  // opacity), no fixed opaque plate that would defeat the transparency the
  // opacity slider is there to control. The tint alpha is NOT multiplied by
  // opacity — like the button/name outlines, bubbles need a legibility
  // floor that survives even a very transparent widget.
  const isDarkBg = relativeLuminance(color) < 0.5;
  document.documentElement.style.setProperty('--log-text', isDarkBg ? 'rgba(245, 245, 245, 0.95)' : 'rgba(20, 20, 20, 0.92)');
  document.documentElement.style.setProperty('--bubble-tint', isDarkBg ? 'rgba(255, 255, 255, 0.14)' : 'rgba(0, 0, 0, 0.06)');
  document.documentElement.style.setProperty('--bubble-border', isDarkBg ? 'rgba(255, 255, 255, 0.35)' : 'rgba(0, 0, 0, 0.25)');

  // Local-msg accent tail: tied to the widget's OWN color (not the neutral
  // black/white --bubble-tint), a shade darker so the little top-center peak
  // reads as "this came from the title above" rather than blending in.
  document.documentElement.style.setProperty('--local-accent', darkenHexToRgba(color, 0.9, 0.25));
}

function applyPrefsToDom() {
  applyColorVars(prefs.color, prefs.opacity);

  colorEl.value = prefs.color;
  opacityEl.value = String(prefs.opacity);
  alwaysOnTopEl.checked = !!prefs.alwaysOnTop;
  muteEl.checked = !!prefs.mute;
  expandWhenHiddenEl.checked = !!prefs.expandWhenHidden;
  micLanguageEl.value = prefs.micLanguage || 'es';
  updateSpeakerIcon();
}

async function init() {
  prefs = await window.las.getPrefs(agentName);
  applyPrefsToDom();
  try {
    const info = await window.las.getAgentInfo(agentName);
    if (info && info.locale) locale = info.locale;
  } catch (err) {
    console.warn('[widget] could not resolve agent locale, defaulting to en-US:', err);
  }
  try {
    const { wake_enabled } = await window.las.getWakeEnabled(agentName);
    wakeEnabledEl.checked = !!wake_enabled;
  } catch (err) {
    console.warn('[widget] could not resolve wake-enabled state:', err);
  }
}
init();

// ── settings panel ──────────────────────────────────────────────────────────

// Settings is inline now (see index.html), not a full-screen overlay — the
// real name/log stay visible above it, and only the bottom-row face buttons
// (besides gear itself) hide while it's open. Gear toggles it open/closed
// and shows .active ("pressed") while open, both as the visual indicator
// and as the only way back besides re-clicking it.
const SETTINGS_HEIGHT = 360;
let settingsOpen = false;

function setSettingsOpen(open) {
  settingsOpen = open;
  settingsEl.classList.toggle('hidden', !open);
  widgetEl.classList.toggle('settings-open', open);
  gearEl.classList.toggle('active', open);
  window.las.setExpanded(open, SETTINGS_HEIGHT);
  if (open) {
    // Latch the "revealed" state too, so mousemove-driven entrance tracking
    // doesn't undo this the moment settings closes and a mousemove fires.
    revealed = true;
    setReveal(1, { settle: true });
  }
}

gearEl.addEventListener('click', () => setSettingsOpen(!settingsOpen));

async function persist(patch) {
  prefs = await window.las.setPrefs(agentName, patch);
  applyPrefsToDom();
}

colorEl.addEventListener('input', () => persist({ color: colorEl.value }));
opacityEl.addEventListener('input', () => persist({ opacity: Number(opacityEl.value) }));
alwaysOnTopEl.addEventListener('change', () => persist({ alwaysOnTop: alwaysOnTopEl.checked }));
muteEl.addEventListener('change', () => persist({ mute: muteEl.checked }));
expandWhenHiddenEl.addEventListener('change', () => {
  persist({ expandWhenHidden: expandWhenHiddenEl.checked });
  if (!expandWhenHiddenEl.checked) setOcclusionExpanded(false);
});
micLanguageEl.addEventListener('change', () => persist({ micLanguage: micLanguageEl.value }));

// Backend-synced, not electron-store: `las agent focus`'s wake fallback
// (Python, backend/main.py) reads the same flag this checkbox sets.
wakeEnabledEl.addEventListener('change', () => {
  window.las.setWakeEnabled(agentName, wakeEnabledEl.checked);
});

// Door button: mark inactive + close this widget. See main.js's
// agent:deactivate comment — never touches the Claude Code session itself.
doorEl.addEventListener('click', async () => {
  try {
    await window.las.deactivateAgent(agentName);
  } catch (err) {
    console.warn('[widget] deactivate: request failed:', err);
  }
});

// ── expand when hidden (retired Swift "Expand on space change") ────────────
//
// document.visibilitychange on macOS tracks real window occlusion (covered
// by another window, or moved off the active Space) — see main.js's
// window:set-occlusion-expanded comment for why this is the closest
// Electron-only equivalent of the retired NSWindowOcclusionState-based
// mechanism, and why the expanded state is click-through (can never block
// typing into whatever is actually on screen).
//
// Debounced: a brief flicker (e.g. a menu momentarily covering the widget)
// shouldn't trigger a full expand/collapse cycle.

let occlusionExpanded = false;
let visibilityDebounce = null;

// How long to wait, after the widget becomes visible again, before shrinking
// back down to the compact face — separate from the (short, fixed) debounce
// on the way INTO occlusion below. Easy to tune: just this one constant.
const RESTORE_DELAY_MS = 1000;

function setOcclusionExpanded(expanded) {
  if (expanded === occlusionExpanded) return;
  occlusionExpanded = expanded;
  window.las.setOcclusionExpanded(expanded);
  widgetEl.classList.toggle('occlusion-expanded', expanded);
  fitNameToBox();
}

document.addEventListener('visibilitychange', () => {
  if (visibilityDebounce) clearTimeout(visibilityDebounce);
  const hidden = document.visibilityState === 'hidden';
  // Going hidden: short debounce, just enough to skip brief flickers (e.g. a
  // menu momentarily covering the widget). Coming back visible: the longer,
  // configurable RESTORE_DELAY_MS — don't yank the banner away the instant
  // you glance back at the Space.
  visibilityDebounce = setTimeout(() => {
    if (!prefs.expandWhenHidden) return;
    setOcclusionExpanded(hidden);
  }, hidden ? 400 : RESTORE_DELAY_MS);
});

// System sleep/wake: no NEW occlusion notification fires on wake if the
// window's occlusion state is unchanged from before sleep (see main.js's
// powerMonitor 'resume' comment), so a widget that was off-Space going into
// sleep can wake up stuck compact instead of expanded/mosaic. Re-read the
// actual visibilityState immediately (no debounce) rather than waiting on an
// event that may never re-fire.
window.las.onSystemResume(() => {
  if (visibilityDebounce) clearTimeout(visibilityDebounce);
  if (!prefs.expandWhenHidden) return;
  setOcclusionExpanded(document.visibilityState === 'hidden');
});

window.addEventListener('resize', () => fitNameToBox());

// ── hover reveal: cursor-depth-driven face ──────────────────────────────────
//
// Resting face: #name sits centered and scaled up (see widget.css's .name
// transform), door/log/buttonbar invisible. As the cursor crosses in from
// whichever edge of the widget is nearest, --reveal tracks how far it has
// traveled — 0 right at the border, 1 once it has advanced inward by the
// same distance the face buttons already sit inset from that border (the
// widget's own CSS padding, read live rather than hardcoded so this stays
// correct if that padding ever changes). Tracking uses REVEAL_TRACK_MS, a
// small capped duration, rather than 0s: a mouse that crosses the whole
// margin in one fast swipe would otherwise SNAP straight to fully revealed
// with nothing to see — capping the speed means even a fast entrance still
// takes this little bit of time, so the title's slide-and-shrink is always
// visible (the "ilusión de materialidad" this is going for), while staying
// short enough to still read as immediate. A longer, separate duration
// (REVEAL_SETTLE_MS) is only used for the moments where --reveal jumps
// WITHOUT the mouse still driving it: leaving the widget, or a locked state
// (settings open, occlusion-expanded banner) forcing a value.
const REVEAL_TRACK_MS = 70;
const REVEAL_SETTLE_MS = 380;
const REVEAL_INTERACTIVE_THRESHOLD = 0.6;

function revealMarginPx() {
  const cs = getComputedStyle(widgetEl);
  const h = parseFloat(cs.paddingLeft) || 16;
  const v = parseFloat(cs.paddingTop) || 14;
  // The tighter of the two axes — icons are inset by whichever margin is
  // smaller, so that's the depth that should mean "fully revealed".
  return Math.max(4, Math.min(h, v));
}

function setReveal(value, { settle } = {}) {
  const v = Math.max(0, Math.min(1, value));
  widgetEl.style.setProperty('--reveal-speed', `${settle ? REVEAL_SETTLE_MS : REVEAL_TRACK_MS}ms`);
  widgetEl.style.setProperty('--reveal', String(v));
  widgetEl.classList.toggle('reveal-interactive', v >= REVEAL_INTERACTIVE_THRESHOLD);
}

setReveal(0);

// Settings panel (active interaction) and the full-screen occlusion banner
// (its own always-visible centered name, see .occlusion-expanded overrides
// in widget.css) both opt out of mouse-depth-driven reveal entirely.
function revealLocked() {
  return settingsOpen || widgetEl.classList.contains('occlusion-expanded');
}

// Two states, not a value that's recomputed on every mousemove forever:
//
//   - Entering: depth/margin drives --reveal from 0 toward 1, 1:1 with the
//     cursor (no transition) — this is the only part that "follows" the
//     mouse, purely as the entrance gets pushed in from the border.
//   - Revealed (latched once depth crosses the margin): --reveal just STAYS
//     at 1. Mousemove is ignored entirely for reveal purposes from then on —
//     wandering anywhere inside the widget (including right back over the
//     now-visible icons, which necessarily sit at shallow depth) can't
//     recompute anything and yank it back down. This is what fixes the
//     earlier "va para atrás y para adelante" flicker: that came from
//     treating depth as a live value for as long as the cursor stayed
//     inside, instead of a one-shot entrance trigger.
//
// Only mouseleave (debounced below) drops back to Entering/resting.
let revealed = false;

function trackEntrance(depthRatio) {
  if (revealed) return;
  if (depthRatio >= 1) {
    revealed = true;
    setReveal(1, { settle: false });
    return;
  }
  setReveal(depthRatio, { settle: false });
}

// A native mouseleave fires the instant the cursor crosses the widget's
// exact pixel boundary — a window this small means just grazing the edge
// while moving toward something else (or a hair of pointer jitter) reads as
// "left" and yanks the face back to resting mid-interaction. Rather than
// collapsing immediately, arm a short timer instead: only if the cursor is
// STILL outside once it fires (no mousemove/mouseenter cancelled it first)
// do we treat the widget as definitively left. That's the "debounce en
// tiempo" — the nearest thing to a spatial buffer an Electron window this
// size can give us without literally growing the window past the visible
// rounded rect (mouse events simply stop arriving once the cursor is past
// the real window edge, so there's no space to measure "how far outside").
const REVEAL_LEAVE_DEBOUNCE_MS = 260;
let leaveTimer = null;

function cancelPendingLeave() {
  if (leaveTimer) {
    clearTimeout(leaveTimer);
    leaveTimer = null;
  }
}

widgetEl.addEventListener('mousemove', (e) => {
  if (resizing || revealLocked()) return;
  cancelPendingLeave();
  if (revealed) return;
  const rect = widgetEl.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const depth = Math.min(x, rect.width - x, y, rect.height - y);
  trackEntrance(depth / revealMarginPx());
});

widgetEl.addEventListener('mouseenter', () => {
  cancelPendingLeave();
});

widgetEl.addEventListener('mouseleave', () => {
  // Dragging the manual resize handle (see "manual resize" section below)
  // moves the window itself via IPC, which lags the cursor just enough that
  // widgetEl's live getBoundingClientRect() often reads the pointer as
  // outside mid-drag — a real mouseleave that has nothing to do with the
  // user actually leaving. Ignore it entirely while resizing; the drag's
  // own mouseup/mousemove handlers don't touch reveal state at all, so
  // there's nothing here that needs to run once resizing stops either.
  if (revealLocked() || resizing) return;
  cancelPendingLeave();
  leaveTimer = setTimeout(() => {
    leaveTimer = null;
    revealed = false;
    // The only spot that animates with a real transition instead of
    // tracking the cursor 1:1 — settling smoothly back into the centered,
    // scaled-up title card.
    setReveal(0, { settle: true });
  }, REVEAL_LEAVE_DEBOUNCE_MS);
});

// ── message log ─────────────────────────────────────────────────────────────

// Cache of other agents' widget colors (for the external-msg name chip) —
// keyed by agent name, populated lazily via window.las.getPrefs(fromName).
// Same electron-store all widgets share (see main.js's getPrefs), so this is
// just avoiding a repeat IPC round-trip per message from the same sender.
const agentColorCache = new Map();
async function getAgentColor(name) {
  if (agentColorCache.has(name)) return agentColorCache.get(name);
  const p = await window.las.getPrefs(name).catch(() => null);
  const color = (p && p.color) || '#90c060';
  agentColorCache.set(name, color);
  return color;
}

// Three distinct, non-overlapping bubble kinds — none of them merge into
// another (per explicit request: mic dictation must never read as this
// agent's own voice, and an external agent's message must never read as
// either): mic dictation (right, "user-msg", "mic" description), this
// agent's own voice/local widget (small margins both sides, "local-msg", no
// name — a centered accent tail says "the title itself is speaking"
// instead), and messages received from OTHER agents (left, "external-msg",
// always showing the sender's name as a color-chip pill, tinted with THAT
// agent's own widget color — the same color you'd see on their widget).
function appendLogEntry(envelope, { speak } = {}) {
  const row = document.createElement('div');
  // A dictated message is a self-send: {from: agentName, to: agentName,
  // source: 'human'} — see main.js's vortexia:send handler. That's the
  // person dictating TO the agent's inbox, not the agent talking to itself,
  // so it renders as a chat bubble on the right (the "user"/mic side).
  const isOwnDictation = envelope.source === 'human' && envelope.from === agentName && envelope.to === agentName;
  // This agent's own voice output (TTS speak events off the queue) arrives
  // as {from: "queue", to: agentName, kind: "speak"} — see backend/main.py's
  // tts_drainer, which hardcodes from:"queue" rather than the agent's own
  // name. Detect it by kind/the `speak` flag, not by `from`.
  const isOwnVoice = !isOwnDictation && (speak || envelope.kind === 'speak');

  if (isOwnDictation) {
    row.className = 'entry user-msg';
    const bubble = document.createElement('span');
    bubble.className = 'bubble';
    bubble.textContent = envelope.text || '';
    row.appendChild(bubble);
    const desc = document.createElement('span');
    desc.className = 'desc';
    desc.textContent = 'mic';
    row.appendChild(desc);
  } else if (isOwnVoice) {
    row.className = 'entry local-msg' + (speak ? ' speak' : '');
    const bubble = document.createElement('span');
    bubble.className = 'bubble';
    bubble.textContent = envelope.text || '';
    row.appendChild(bubble);
  } else {
    row.className = 'entry external-msg' + (speak ? ' speak' : '');
    const bubble = document.createElement('span');
    bubble.className = 'bubble';
    bubble.textContent = envelope.text || '';
    row.appendChild(bubble);
    const chip = document.createElement('span');
    chip.className = 'from-chip';
    chip.textContent = envelope.from || '?';
    row.appendChild(chip);
    // Color-fetch is async; the chip renders immediately with a neutral
    // fallback tint and is upgraded in place once the sender's own widget
    // color resolves — never blocks/delays the message itself appearing.
    getAgentColor(envelope.from).then((color) => {
      chip.style.background = hexToRgba(color, 0.32);
      chip.style.borderColor = hexToRgba(color, 0.7);
    });
  }
  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;

  // Keep the log from growing unbounded.
  while (logEl.children.length > 100) logEl.removeChild(logEl.firstChild);
}

// ── speech (local Kokoro TTS) ────────────────────────────────────────────────
//
// Speak-request convention (also documented in main.js): an inbox envelope
// with "kind": "speak" -> { kind: "speak", from, to, text, voice?, ts }.
// This is our own convention for this pass (PROTOCOL.md doesn't define one
// yet); any future vortexia-side convention should update both places.
//
// Replaced window.speechSynthesis (Chromium's built-in TTS — noticeably
// worse than macOS's own `say` voices, confirmed by the user) with Kokoro-82M
// run locally via kokoro-js: main.js does the ONNX inference (see its "local
// text-to-speech" section) and hands back a WAV buffer for this process to
// play. window.las.ttsVoices replaces speechSynthesis.getVoices() as the pool
// pickVoice() hashes agents into — same function, same locale-fallback
// behavior, just a different (better-sounding, and free) voice source.

async function speak(text) {
  if (prefs.mute) return;
  const { voice, warning } = window.las.pickVoice(agentName, locale, window.las.ttsVoices);
  if (warning) console.warn('[widget]', warning);
  if (!voice) return;
  let result;
  try {
    result = await window.las.synthesizeSpeech(text, voice.name, voice.kokoroLang);
  } catch (err) {
    console.warn('[widget] synthesizeSpeech IPC failed', err);
    return;
  }
  if (!result || !result.ok) {
    console.warn('[widget] tts synthesis failed', result && result.error);
    return;
  }
  const url = URL.createObjectURL(new Blob([result.wav], { type: 'audio/wav' }));
  const audioEl = new Audio(url);
  audioEl.addEventListener('ended', () => URL.revokeObjectURL(url));
  audioEl.addEventListener('error', () => URL.revokeObjectURL(url));
  audioEl.play().catch((err) => console.warn('[widget] audio playback failed', err));
}

// Set by runMicSelfTest() while it's waiting for the live session's "OK"
// reply — see the mic self-test section below. Routed through this shared
// handler (rather than a fresh window.las.onVortexiaMessage() registration
// per self-test) because preload.js exposes no removeListener: registering
// a new one on every double-click would leak an ipcRenderer listener per
// self-test, never cleaned up.
let pendingMicSelfTestResolve = null;

window.las.onVortexiaMessage((envelope) => {
  console.log('[widget] received', JSON.stringify(envelope));
  if (envelope && envelope.kind === 'mic-selftest-pong') {
    // Silent, mechanical confirmation published directly by `las agent
    // listen` itself (cli/commands/agents.py) — proves the mic -> vortexia
    // -> a live terminal-side listener pipe works, independent of whether
    // an LLM session is attached. Deliberately NOT spoken and NOT shown as
    // a chat bubble — an audible/visible "OK" here would misrepresent mere
    // plumbing as a real reply. The audible "OK" below (kind: 'speak') is
    // the separate, optional confirmation that an LLM actually answered.
    if (pendingMicSelfTestResolve && envelope.to === agentName) {
      pendingMicSelfTestResolve(true);
      pendingMicSelfTestResolve = null;
    }
    return;
  }
  if (envelope && envelope.kind === 'speak') {
    appendLogEntry(envelope, { speak: true });
    speak(envelope.text || '');
    if (
      pendingMicSelfTestResolve &&
      envelope.to === agentName &&
      typeof envelope.text === 'string' &&
      envelope.text.trim().toLowerCase() === 'ok'
    ) {
      pendingMicSelfTestResolve(true);
      pendingMicSelfTestResolve = null;
    }
  } else if (envelope) {
    appendLogEntry(envelope);
  }
});

window.las.onVortexiaStatus((status) => {
  if (!status.connected) {
    console.warn('[widget] vortexia not connected:', status.error);
  }
});

// ── manual resize (frameless window has no native resize border) ───────────

const resizeHandleEl = document.getElementById('resizeHandle');
let resizing = false;
let lastX = 0;
let lastY = 0;

resizeHandleEl.addEventListener('mousedown', (e) => {
  resizing = true;
  lastX = e.screenX;
  lastY = e.screenY;
  e.preventDefault();
});

window.addEventListener('mousemove', (e) => {
  if (!resizing) return;
  const dw = e.screenX - lastX;
  const dh = e.screenY - lastY;
  lastX = e.screenX;
  lastY = e.screenY;
  window.las.resizeBy(dw, dh);
});

window.addEventListener('mouseup', () => {
  resizing = false;
});

// ── face buttons ─────────────────────────────────────────────────────────
//
// Restores the buttons the retired Swift widget (widget/tray.swift) had on
// its compact face: speaker (mute toggle), mic (dictation), clear (log),
// terminal (command palette), focus/scope (focus + link a TTY). The gear
// button/settings panel above are untouched — this section is purely
// additive.

// -- speaker: one-click mute toggle ------------------------------------------

const speakerEl = document.getElementById('speaker');

function updateSpeakerIcon() {
  speakerEl.innerHTML = prefs.mute ? '&#128263;' : '&#128266;'; // 🔇 / 🔊
  speakerEl.classList.toggle('active', !!prefs.mute);
  speakerEl.title = prefs.mute ? 'Unmute' : 'Mute';
}

speakerEl.addEventListener('click', async () => {
  await persist({ mute: !prefs.mute });
});

// -- clear: type "/clear" into the linked terminal(s) ------------------------
//
// Faithful port of the retired Swift clearSession(), which did
// injectToSession("/clear", source: "raw") — literally typing "/clear" into
// the agent's live iTerm2 session(s). That raw-terminal-write mechanism
// (distinct from the retired inter-agent inject/messaging pipeline — see
// main.js's agent:focus/agent:tty-write comments) still exists on the
// backend and still works; an agent can have more than one linked terminal
// open, so this writes to all of them (backend: POST /agents/{name}/tty-write
// with no `tty` -> _find_all_claude_ttys, not just one selected session).
// Also clears this window's own visible log, which is free and harmless.

document.getElementById('clear').addEventListener('click', async () => {
  logEl.innerHTML = '';
  try {
    const result = await window.las.writeToTty(agentName, '/clear');
    if (!result || !result.written || result.written.length === 0) {
      console.warn('[widget] /clear did not reach any linked terminal:', result);
    }
  } catch (err) {
    console.warn('[widget] tty-write failed:', err);
  }
});

// -- mic: dictation via local, offline Whisper transcription ----------------
//
// Chromium's built-in SpeechRecognition/webkitSpeechRecognition is a cloud
// service tied to a Google API key that only official Chrome builds have —
// verified live, it always fails with error:"network" in Electron even
// though getUserMedia (mic access) works fine, and there is no
// flag/permission fix (see main.js's "audio transcription" section for the
// full writeup). Replacement: this still records with MediaRecorder (same
// getUserMedia mic access, same click-to-start/click-to-stop UX as before),
// but instead of a cloud recognizer it decodes the clip to raw PCM here in
// the renderer (Web Audio API — a browser API, no Node/sandbox issue) and
// hands that PCM to main.js's local Whisper pipeline over IPC. A result is
// published to this agent's OWN vortexia inbox (not typed into a live TTY —
// that mechanism is retired) so the /las-agent skill picks it up at the
// start of this agent's next Claude Code session (see CLAUDE.md) — exactly
// the same destination the old SpeechRecognition.onresult used.

const micEl = document.getElementById('mic');
const MAX_RECORDING_MS = 600000; // 10 min safety net if the user forgets to click stop

let mediaRecorder = null;
let recordedChunks = [];
let micState = 'idle'; // 'idle' | 'listening' | 'transcribing'
let maxDurationTimer = null;
let countdownTimers = [];

function setMicState(next) {
  micState = next;
  micEl.classList.toggle('active', next === 'listening');
  micEl.classList.toggle('busy', next === 'transcribing');
  if (next === 'listening') {
    micEl.title = 'Recording… click to stop';
  } else if (next === 'transcribing') {
    micEl.title = 'Transcribing…';
  } else {
    micEl.title = 'Dictate (click to start/stop, double-click to test mic)';
  }
}

// Pushed from main.js during transcribeAudio — distinguishes "downloading
// the model, first use only" from ordinary inference so the button doesn't
// just look frozen on the very first dictation on a machine.
window.las.onAudioStatus((status) => {
  if (micState !== 'transcribing' || !status) return;
  if (status.state === 'loading-model') {
    micEl.title = 'Downloading speech model (first use only)…';
  } else if (status.state === 'transcribing') {
    micEl.title = 'Transcribing…';
  }
});

/**
 * Decode a recorded Blob (webm/opus from MediaRecorder) down to mono 16kHz
 * Float32 PCM — the sample format @xenova/transformers' Whisper ASR
 * pipeline expects. An OfflineAudioContext does the resample in one shot
 * instead of a hand-rolled resampler.
 */
async function blobToMono16kPCM(blob) {
  const arrayBuffer = await blob.arrayBuffer();
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  const decodeCtx = new AudioCtx();
  let decoded;
  try {
    decoded = await decodeCtx.decodeAudioData(arrayBuffer);
  } finally {
    decodeCtx.close();
  }
  const targetRate = 16000;
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * targetRate), targetRate);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start(0);
  const rendered = await offline.startRendering();
  return rendered.getChannelData(0);
}

// -- countdown beeps across the MAX_RECORDING_MS safety-net window ----------
// Purely a "how much time is left before this gets force-stopped" awareness
// aid, distinct from any transcription/model concern — a calm low pip at the
// halfway point, then rising urgency as the cutoff nears (10s, then 5s)
// before stopRecordingAndTranscribe() fires.

let sharedAudioCtx = null;
function playBeep(freq, durationMs) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!sharedAudioCtx) sharedAudioCtx = new AudioCtx();
    const ctx = sharedAudioCtx;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    osc.connect(gain);
    gain.connect(ctx.destination);
    const now = ctx.currentTime;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.25, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + durationMs / 1000);
    osc.start(now);
    osc.stop(now + durationMs / 1000 + 0.02);
  } catch (err) {
    console.warn('[widget] mic: beep failed:', err);
  }
}

function scheduleCountdownBeeps() {
  clearCountdownTimers();
  countdownTimers.push(setTimeout(() => playBeep(440, 110), MAX_RECORDING_MS / 2)); // halfway
  countdownTimers.push(setTimeout(() => playBeep(660, 110), MAX_RECORDING_MS - 10000)); // 10s left
  countdownTimers.push(setTimeout(() => playBeep(780, 110), MAX_RECORDING_MS - 5000)); // 5s left
}

function clearCountdownTimers() {
  countdownTimers.forEach(clearTimeout);
  countdownTimers = [];
}

// -- mic self-test (double-click): confirms the mic + dictation pipeline is
// actually live, without having to talk into it and wait for a transcript.
// Answers "me escuchás? estás ok?" instantly instead of after 5 minutes of
// dictating into a dead mic.
//
// A real end-to-end test, not just a canned reply: getUserMedia (mic
// capture) succeeding only gets a neutral 🎙️ toast — it says nothing about
// whether a live Claude Code session is actually attached and listening on
// the other end. An earlier version spoke a hardcoded "OK" back through the
// TTS queue on success, which gave false confidence even with no session
// running at all; a later version fixed the canned reply but still flashed
// 👍 immediately on mic capture alone, before any reply could possibly have
// arrived, which was the same false-positive under a different name. This
// version publishes a real self-dictation ping into the agent's OWN
// vortexia inbox (window.las.sendToSelf — the exact same path a real mic
// dictation uses), then actually WAITS (see waitForMicSelfTestReply, up to
// MIC_SELFTEST_REPLY_TIMEOUT_MS) for a reply before showing 👍 or 👎. Two
// independent, layered confirmations can satisfy that wait:
//   1. `las agent listen` (cli/commands/agents.py) answers the sentinel
//      itself, silently and mechanically, the instant it's received — a
//      'mic-selftest-pong' envelope, no TTS, no LLM involved. This alone
//      proves the mic -> vortexia -> a live terminal-side listener pipe is
//      intact, which is the whole point of a *self*-test: it should not
//      require an LLM to be paying attention just to prove the plumbing
//      works.
//   2. The `las-agent` skill (see CLAUDE.md / its "Escucha en vivo"
//      section) separately tells an attached LLM session to also speak
//      "OK" back out loud on seeing this same sentinel — optional, audible
//      backup coverage on top of #1, not required for 👍.
// If neither arrives in time, that itself is the useful signal — nothing
// at all is listening — and the UI now actually shows 👎 for it instead of
// a thumbs-up regardless.
const MIC_SELFTEST_PING = '[las-mic-selftest] reply with just "OK" to confirm this session is listening.';
const MIC_SELFTEST_REPLY_TIMEOUT_MS = 8000;

// Resolves true if a live session's "OK" comes back in time, false on
// timeout. See pendingMicSelfTestResolve above for how the reply is caught.
// micSelfTestGeneration guards against a double-click fired again while a
// prior self-test is still waiting (micState alone doesn't block this,
// since self-test never leaves 'idle'): without it, the first call's own
// timeout would null out the second call's still-pending resolver.
let micSelfTestGeneration = 0;
function waitForMicSelfTestReply(timeoutMs) {
  const generation = ++micSelfTestGeneration;
  return new Promise((resolve) => {
    let settled = false;
    pendingMicSelfTestResolve = (ok) => {
      if (settled) return;
      settled = true;
      resolve(ok);
    };
    setTimeout(() => {
      if (settled) return;
      settled = true;
      if (micSelfTestGeneration === generation) pendingMicSelfTestResolve = null;
      resolve(false);
    }, timeoutMs);
  });
}

function showMicToast(emoji) {
  const toast = document.createElement('span');
  toast.className = 'mic-test-toast';
  toast.textContent = emoji;
  micEl.appendChild(toast);
  toast.addEventListener('animationend', () => toast.remove(), { once: true });
  // Safety net in case animationend never fires (e.g. window backgrounded).
  setTimeout(() => toast.remove(), 1500);
}

async function runMicSelfTest() {
  if (micState !== 'idle') return; // don't interrupt a real recording/transcription
  window.las.log('info', 'mic', 'self-test (double-click): starting');
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    window.las.log('error', 'mic', `self-test failed: getUserMedia error: ${err && err.message ? err.message : err}`);
    showMicToast('👎');
    return;
  }
  const track = stream.getAudioTracks()[0];
  const live = !!track && track.readyState === 'live';
  stream.getTracks().forEach((t) => t.stop());
  if (live) {
    window.las.log('info', 'mic', 'self-test ok: mic capture is live — pinging own inbox for a real session to answer');
    // Capture-only feedback, distinct from the round-trip verdict below —
    // this alone used to be shown as 👍, which is exactly the false
    // positive this test exists to catch: mic capture working says nothing
    // about whether a live session is attached to answer.
    showMicToast('🎙️');
    const sendResult = await window.las.sendToSelf(agentName, MIC_SELFTEST_PING);
    if (!sendResult || !sendResult.ok) {
      window.las.log('warn', 'mic', `self-test ping failed to publish: ${sendResult && sendResult.error}`);
      showMicToast('👎');
      return;
    }
    const replied = await waitForMicSelfTestReply(MIC_SELFTEST_REPLY_TIMEOUT_MS);
    if (replied) {
      window.las.log('info', 'mic', 'self-test ok: a live session replied "OK" — round trip confirmed');
      showMicToast('👍');
    } else {
      window.las.log(
        'warn',
        'mic',
        `self-test: mic capture works but no live session answered within ${MIC_SELFTEST_REPLY_TIMEOUT_MS}ms — is a Claude Code session running the las-agent live listener for this agent?`
      );
      showMicToast('👎');
    }
  } else {
    window.las.log('error', 'mic', 'self-test failed: audio track not live');
    showMicToast('👎');
  }
}

async function stopRecordingAndTranscribe() {
  clearCountdownTimers();
  if (maxDurationTimer) {
    clearTimeout(maxDurationTimer);
    maxDurationTimer = null;
  }
  const recorder = mediaRecorder;
  mediaRecorder = null;
  if (!recorder) return;

  window.las.log('info', 'mic', 'stop clicked — flushing recorder');
  await new Promise((resolve) => {
    if (recorder.state === 'inactive') {
      resolve();
      return;
    }
    recorder.addEventListener('stop', resolve, { once: true });
    recorder.stop();
  });
  recorder.stream.getTracks().forEach((track) => track.stop());

  if (!recordedChunks.length) {
    window.las.log('warn', 'mic', 'stop: no audio chunks recorded — nothing to transcribe');
    setMicState('idle');
    return;
  }

  setMicState('transcribing');
  try {
    const blob = new Blob(recordedChunks, { type: recorder.mimeType || 'audio/webm' });
    window.las.log('info', 'mic', `decoding blob: ${blob.size} bytes, type=${blob.type}`);
    const pcm = await blobToMono16kPCM(blob);
    window.las.log('info', 'mic', `decoded: ${pcm.length} samples (~${(pcm.length / 16000).toFixed(1)}s)`);
    // Dictation language is a separate, user-chosen setting (prefs.micLanguage)
    // — NOT derived from the agent's TTS voice locale. An agent can speak
    // back in English (its voice) while the person dictating to it speaks
    // Spanish; coupling the two silently mistranscribed Spanish speech as
    // English whenever an agent's registered voice was English. 'auto' lets
    // Whisper auto-detect (pass no language hint).
    const languageHint = prefs.micLanguage && prefs.micLanguage !== 'auto' ? prefs.micLanguage : null;
    const result = await window.las.transcribeAudio(pcm.buffer, languageHint);
    window.las.log(
      'info',
      'mic',
      `transcribeAudio returned ok=${!!(result && result.ok)} chars=${result && result.text ? result.text.length : 0}`
    );
    if (result && result.ok && result.text) {
      // Publish via vortexia — NOT a direct live write into the linked
      // terminal. An earlier pass here did the opposite (writeToTty first,
      // vortexia only as a fallback), faithfully porting the retired Swift
      // injectToSession's live-TTY-write behavior. Reversed on explicit
      // request: direct terminal injection depends on iTerm2/AppleScript
      // specifically and isn't portable across terminal apps (or platforms —
      // Windows has no equivalent at all), which is exactly the class of
      // mechanism this whole project moved away from in favor of vortexia.
      // The Clear button still uses writeToTty on purpose — "/clear" is
      // meant to act on a live session right now, a different use case from
      // dictation, which is fine landing in the inbox for the /las-agent
      // skill to pick up at the next session start (see CLAUDE.md).
      //
      // Don't also appendLogEntry here — this agent is subscribed to its own
      // inbox topic, so the publish loops back through onVortexiaMessage and
      // displays itself; appending it here too would show the line twice.
      const sendResult = await window.las.sendToSelf(agentName, result.text);
      if (!sendResult || !sendResult.ok) {
        window.las.log('error', 'mic', `failed to publish dictation to own inbox: ${sendResult && sendResult.error}`);
        console.warn('[widget] mic: failed to publish dictation to own inbox:', sendResult && sendResult.error);
      }
    } else if (result && !result.ok) {
      window.las.log('error', 'mic', `transcription failed: ${result.error}`);
      console.warn('[widget] mic: transcription failed:', result.error);
    } else {
      window.las.log('warn', 'mic', 'transcription returned ok but empty text — nothing published');
    }
  } catch (err) {
    window.las.log('error', 'mic', `transcription pipeline failed: ${err && err.stack ? err.stack : err}`);
    console.warn('[widget] mic: transcription pipeline failed:', err);
  } finally {
    setMicState('idle');
  }
}

async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    window.las.log('error', 'mic', `getUserMedia failed: ${err && err.message ? err.message : err}`);
    console.warn('[widget] mic: getUserMedia failed:', err);
    return;
  }
  recordedChunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.addEventListener('dataavailable', (e) => {
    if (e.data && e.data.size) recordedChunks.push(e.data);
  });
  mediaRecorder.start();
  setMicState('listening');
  window.las.log('info', 'mic', 'recording started');
  maxDurationTimer = setTimeout(() => {
    window.las.log('warn', 'mic', `max recording duration (${MAX_RECORDING_MS}ms) hit — auto-stopping`);
    stopRecordingAndTranscribe();
  }, MAX_RECORDING_MS);
  scheduleCountdownBeeps();
}

// Single click toggles start/stop; double-click runs the self-test instead.
// Click events fire immediately (no built-in delay), so a plain 'click'
// listener would act on BOTH clicks of a double-click before 'dblclick' ever
// fires. Standard workaround: delay the single-click action briefly and
// cancel it if a second click arrives in time.
let micClickTimer = null;
micEl.addEventListener('click', (e) => {
  if (e.detail >= 2) return; // handled by dblclick below
  micClickTimer = setTimeout(() => {
    micClickTimer = null;
    if (micState === 'listening') {
      stopRecordingAndTranscribe();
    } else if (micState === 'idle') {
      startRecording();
    }
    // clicks while 'transcribing' are ignored — nothing meaningful to toggle
  }, 220);
});

micEl.addEventListener('dblclick', () => {
  if (micClickTimer) {
    clearTimeout(micClickTimer);
    micClickTimer = null;
  }
  runMicSelfTest();
});

// -- focus/scope: tap = focus, right-click/long-press = link a TTY ----------
//
// True native OS drag-and-drop (dragging the button onto an arbitrary
// terminal window, as the Swift ScopeDragButton did via NSDraggingSource +
// a pasteboard string) is out of scope for this pass — see report. This
// implements the task's documented fallback instead: a press-and-hold (or
// right-click) opens a small picker of this agent's candidate TTYs
// (GET /agents/{name}/ttys), and picking one calls POST
// /agents/{name}/pin-tty to link it, matching what a completed drag would
// have done on the backend side.

const focusEl = document.getElementById('focus');
const ttyPickerEl = document.getElementById('ttyPicker');
const ttyListEl = document.getElementById('ttyList');
const closeTtyPickerEl = document.getElementById('closeTtyPicker');

focusEl.addEventListener('click', async () => {
  try {
    await window.las.focusAgent(agentName);
  } catch (err) {
    console.warn('[widget] focus: request failed:', err);
  }
});

let longPressTimer = null;
focusEl.addEventListener('mousedown', () => {
  longPressTimer = setTimeout(() => openTtyPicker(), 600);
});
focusEl.addEventListener('mouseup', () => {
  if (longPressTimer) clearTimeout(longPressTimer);
});
focusEl.addEventListener('mouseleave', () => {
  if (longPressTimer) clearTimeout(longPressTimer);
});
focusEl.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  openTtyPicker();
});

async function openTtyPicker() {
  ttyListEl.innerHTML = '<div class="command-row">Loading…</div>';
  ttyPickerEl.classList.remove('hidden');
  window.las.setExpanded(true);
  let result;
  try {
    result = await window.las.getAgentTtys(agentName);
  } catch (err) {
    ttyListEl.innerHTML = `<div class="command-row">Error: ${String(err)}</div>`;
    return;
  }
  const ttys = (result && result.ttys) || [];
  if (!ttys.length) {
    ttyListEl.innerHTML = '<div class="command-row">No candidate TTYs found for this agent.</div>';
    return;
  }
  ttyListEl.innerHTML = '';
  for (const tty of ttys) {
    const row = document.createElement('div');
    row.className = 'command-row';
    const label = document.createElement('span');
    label.className = 'command-label';
    label.textContent = tty;
    row.appendChild(label);
    const pinBtn = document.createElement('button');
    pinBtn.textContent = 'Link';
    pinBtn.addEventListener('click', async () => {
      await window.las.pinTty(agentName, tty);
      ttyPickerEl.classList.add('hidden');
      window.las.setExpanded(false);
    });
    row.appendChild(pinBtn);
    ttyListEl.appendChild(row);
  }
}

closeTtyPickerEl.addEventListener('click', () => {
  ttyPickerEl.classList.add('hidden');
  window.las.setExpanded(false);
});

// -- terminal: command palette ------------------------------------------------

const terminalEl = document.getElementById('terminal');
const commandsEl = document.getElementById('commands');
const commandsListEl = document.getElementById('commandsList');
const commandsAddEl = document.getElementById('commandsAdd');
const closeCommandsEl = document.getElementById('closeCommands');

const commandEditEl = document.getElementById('commandEdit');
const cmdLabelEl = document.getElementById('cmdLabel');
const cmdKindEl = document.getElementById('cmdKind');
const cmdCwdRowEl = document.getElementById('cmdCwdRow');
const cmdCommandRowEl = document.getElementById('cmdCommandRow');
const cmdTextRowEl = document.getElementById('cmdTextRow');
const cmdCwdEl = document.getElementById('cmdCwd');
const cmdCommandEl = document.getElementById('cmdCommand');
const cmdTextEl = document.getElementById('cmdText');
const cmdSaveEl = document.getElementById('cmdSave');
const cmdCancelEl = document.getElementById('cmdCancel');

let editingIndex = null; // null => adding a new command

terminalEl.addEventListener('click', async () => {
  if (!commandsEl.classList.contains('hidden')) {
    commandsEl.classList.add('hidden');
    window.las.setExpanded(false);
    return;
  }
  await renderCommandsList();
  commandsEl.classList.remove('hidden');
  window.las.setExpanded(true);
});

closeCommandsEl.addEventListener('click', () => {
  commandsEl.classList.add('hidden');
  window.las.setExpanded(false);
});

async function renderCommandsList() {
  const commands = await window.las.getCommands(agentName);
  commandsListEl.innerHTML = '';
  if (!commands.length) {
    commandsListEl.innerHTML = '<div class="command-row">No saved commands yet.</div>';
  }
  commands.forEach((cmd, index) => {
    const row = document.createElement('div');
    row.className = 'command-row';

    const kindTag = document.createElement('span');
    kindTag.className = 'command-kind';
    kindTag.textContent = cmd.kind === 'sendMessage' ? 'MSG' : 'TERM';
    row.appendChild(kindTag);

    const label = document.createElement('span');
    label.className = 'command-label';
    label.textContent = cmd.label || '(untitled)';
    label.title = 'Run';
    label.addEventListener('click', () => runCommand(cmd));
    row.appendChild(label);

    const editBtn = document.createElement('button');
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => openCommandEdit(cmd, index));
    row.appendChild(editBtn);

    const delBtn = document.createElement('button');
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', async () => {
      const next = commands.slice();
      next.splice(index, 1);
      await window.las.setCommands(agentName, next);
      await renderCommandsList();
    });
    row.appendChild(delBtn);

    commandsListEl.appendChild(row);
  });
}

function runCommand(cmd) {
  commandsEl.classList.add('hidden');
  window.las.setExpanded(false);
  if (cmd.kind === 'sendMessage') {
    window.las.vortexiaSend(agentName, cmd.text || '');
  } else {
    window.las.openTerminal(cmd.cwd || '', cmd.command || '');
  }
}

function updateCommandEditRows() {
  const isTerminal = cmdKindEl.value === 'openTerminal';
  cmdCwdRowEl.style.display = isTerminal ? 'flex' : 'none';
  cmdCommandRowEl.style.display = isTerminal ? 'flex' : 'none';
  cmdTextRowEl.style.display = isTerminal ? 'none' : 'flex';
}

cmdKindEl.addEventListener('change', updateCommandEditRows);

function openCommandEdit(cmd, index) {
  editingIndex = typeof index === 'number' ? index : null;
  cmdLabelEl.value = cmd ? cmd.label || '' : '';
  cmdKindEl.value = cmd ? cmd.kind : 'openTerminal';
  cmdCwdEl.value = cmd ? cmd.cwd || '' : '';
  cmdCommandEl.value = cmd ? cmd.command || '' : '';
  cmdTextEl.value = cmd ? cmd.text || '' : '';
  updateCommandEditRows();
  commandsEl.classList.add('hidden');
  commandEditEl.classList.remove('hidden');
}

commandsAddEl.addEventListener('click', () => openCommandEdit(null, null));
cmdCancelEl.addEventListener('click', () => {
  commandEditEl.classList.add('hidden');
  commandsEl.classList.remove('hidden');
});

cmdSaveEl.addEventListener('click', async () => {
  const kind = cmdKindEl.value === 'sendMessage' ? 'sendMessage' : 'openTerminal';
  const label = cmdLabelEl.value.trim() || (kind === 'sendMessage' ? (cmdTextEl.value.trim() || 'message') : (cmdCommandEl.value.trim() || 'terminal'));
  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    label,
    kind,
    cwd: cmdCwdEl.value.trim(),
    command: cmdCommandEl.value.trim(),
    text: cmdTextEl.value.trim(),
  };
  const commands = await window.las.getCommands(agentName);
  if (editingIndex === null) {
    commands.push(entry);
  } else {
    entry.id = commands[editingIndex].id;
    commands[editingIndex] = entry;
  }
  await window.las.setCommands(agentName, commands);
  commandEditEl.classList.add('hidden');
  commandsEl.classList.remove('hidden');
  await renderCommandsList();
});
