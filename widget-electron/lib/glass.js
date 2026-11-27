'use strict';
/**
 * Native Liquid Glass behind a BrowserWindow (macOS 26+).
 *
 * The real material — the Dock's: highly transparent, a mild blur, the
 * refraction at the edges — is AppKit's NSGlassEffectView, which Electron has
 * no binding for. This talks to it through the Objective-C runtime via koffi
 * (the same FFI lib/spaces.js uses for the Spaces API — no native addon, no
 * build step): the window's content NSView gets a glass view inserted as its
 * lowest subview, autoresizing with the window, so the page paints over the
 * glass and the glass samples the desktop behind the (transparent) window —
 * measured over red/blue stripes: the backdrop stays recognisable (mild blur),
 * keeps ~95% of its color, and the tint rides on top.
 *
 * `available()` is the capability check main.js's "glass look" falls back on:
 * no NSGlassEffectView class (macOS < 26) → vibrancy. Every call here is
 * synchronous on the main thread, which is where AppKit wants it.
 */
const supported = process.platform === 'darwin';

/** The tint is the agent color at this alpha; the opacity pref scales the whole
 * glass instead (see attach): less opacity = more of the sharp desktop through
 * it, as if the glass moved closer to what is behind. */
const TINT_ALPHA = 0.45;
const MIN_GLASS_ALPHA = 0.08;
const DEFAULT_RADIUS = 15;
const NSViewWidthSizable = 2;
const NSViewHeightSizable = 16;
const NSWindowBelow = -1;
const NSGlassEffectViewStyleRegular = 0;

let api = null;
let initError = null;

function init() {
  if (api || initError) return;
  if (!supported) {
    initError = new Error('native glass is macOS only');
    return;
  }
  try {
    const koffi = require('koffi');
    const objc = koffi.load('/usr/lib/libobjc.A.dylib');
    const getClass = objc.func('void* objc_getClass(const char*)');
    const sel = objc.func('void* sel_registerName(const char*)');
    // objc_msgSend is declared variadic but every method has a fixed
    // signature (on arm64 the two ABIs differ), so each shape gets its own
    // fixed prototype decoded from the one symbol.
    const msgSend = objc.symbol('objc_msgSend');
    const proto = (sig) => koffi.decode(msgSend, koffi.proto(sig));
    koffi.struct('LASNSRect', { x: 'double', y: 'double', w: 'double', h: 'double' });
    const send = {
      obj: proto('void* las_msgSend_obj(void*, void*)'),
      rect: proto('LASNSRect las_msgSend_getRect(void*, void*)'),
      initRect: proto('void* las_msgSend_initRect(void*, void*, LASNSRect)'),
      double: proto('void las_msgSend_double(void*, void*, double)'),
      long: proto('void las_msgSend_long(void*, void*, long)'),
      ulong: proto('void las_msgSend_ulong(void*, void*, unsigned long)'),
      ptr: proto('void las_msgSend_ptr(void*, void*, void*)'),
      bool: proto('void las_msgSend_bool(void*, void*, bool)'),
      responds: proto('bool las_msgSend_responds(void*, void*, void*)'),
      addSubview: proto('void las_msgSend_addSubview(void*, void*, void*, long, void*)'),
      color: proto('void* las_msgSend_color(void*, void*, double, double, double, double)'),
    };
    const glassClass = getClass('NSGlassEffectView');
    if (!glassClass) {
      initError = new Error('NSGlassEffectView is not in this macOS (needs 26+)');
      return;
    }
    api = { getClass, sel, send, glassClass, colorClass: getClass('NSColor') };
  } catch (err) {
    initError = err;
  }
}

/** @returns {boolean} the real material can be used here */
function available() {
  init();
  return !!api;
}

/** Why native glass is off, for the log; '' when it is on. */
function status() {
  init();
  if (!api) return initError ? initError.message : 'unavailable';
  return keepTintSupported === false ? 'native (tint mutes when not key: no set_tintOpacityReduced:)' : 'native';
}

/** '#rrggbb' → [r, g, b] in 0..1; anything else → a neutral gray. */
function parseHex(color) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(color || '').trim());
  if (!m) return [0.56, 0.61, 0.69];
  const n = parseInt(m[1], 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

function tintColor(color) {
  const [r, g, b] = parseHex(color);
  return api.send.color(api.colorClass, api.sel('colorWithSRGBRed:green:blue:alpha:'), r, g, b, TINT_ALPHA);
}
/** Full glass down to FULL_GLASS_AT on the slider, then it thins out. */
const FULL_GLASS_AT = 0.7;
function glassAlpha(opacity) {
  const o = Number(opacity);
  return Math.max(MIN_GLASS_ALPHA, Math.min(1, (Number.isFinite(o) ? o : 0.72) / FULL_GLASS_AT));
}

/**
 * AppKit mutes the tint of a glass view whose window is not key (the way it
 * grays inactive windows) — a widget is almost never key, so its color
 * would be gone most of the time. The view's private flag behind that is
 * reset by AppKit on every key-state change, so attach() re-applies it on
 * the window's focus/blur/show (the only moments the key state moves).
 */
let keepTintSupported = null;
function keepTint(glass) {
  const { sel, send } = api;
  const setter = sel('set_tintOpacityReduced:');
  if (keepTintSupported === null) keepTintSupported = !!send.responds(glass, sel('respondsToSelector:'), setter);
  if (!keepTintSupported) return;
  send.bool(glass, setter, false);
}
/** AppKit recomputes the mute on its next run-loop turns after a key-state
 * move, so one call right away is not enough: again shortly after. */
const KEEP_TINT_DELAYS_MS = [0, 60, 400];
function keepTintSoon(win, glass) {
  for (const ms of KEEP_TINT_DELAYS_MS) {
    setTimeout(() => {
      if (win.isDestroyed() || !attached.has(win)) return;
      keepTint(glass);
    }, ms);
  }
}

/** @type {WeakMap<import('electron').BrowserWindow, {glass: bigint, onKey: () => void}>} window → its glass view */
const attached = new WeakMap();

/**
 * Put the glass under the window's page. Idempotent per window.
 * @param {import('electron').BrowserWindow} win a `transparent: true` window
 * @param {{color?: string, opacity?: number, radius?: number}} [opts]
 * @returns {boolean} attached (false: unsupported here, or the window is gone)
 */
function attach(win, { color, opacity, radius = DEFAULT_RADIUS } = {}) {
  if (!available() || !win || win.isDestroyed()) return false;
  if (attached.has(win)) {
    setTint(win, color, opacity);
    return true;
  }
  const { sel, send } = api;
  const view = win.getNativeWindowHandle().readBigUInt64LE(0); // the NSView* electron hands out
  const nswin = send.obj(view, sel('window'));
  const content = send.obj(nswin, sel('contentView'));
  const bounds = send.rect(content, sel('bounds'));
  let glass = send.obj(api.glassClass, sel('alloc'));
  glass = send.initRect(glass, sel('initWithFrame:'), bounds);
  send.double(glass, sel('setCornerRadius:'), radius);
  send.long(glass, sel('setStyle:'), NSGlassEffectViewStyleRegular);
  send.ptr(glass, sel('setTintColor:'), tintColor(color));
  send.double(glass, sel('setAlphaValue:'), glassAlpha(opacity));
  send.ulong(glass, sel('setAutoresizingMask:'), NSViewWidthSizable | NSViewHeightSizable);
  send.addSubview(content, sel('addSubview:positioned:relativeTo:'), glass, NSWindowBelow, null);
  send.obj(glass, sel('release')); // the superview owns it now (see detach)
  const onKey = () => keepTintSoon(win, glass);
  for (const ev of ['show', 'ready-to-show', 'focus', 'blur']) win.on(ev, onKey);
  attached.set(win, { glass, onKey });
  win.once('closed', () => attached.delete(win));
  keepTintSoon(win, glass);
  return true;
}

/** Re-tint an attached window (the agent's color or opacity pref changed). */
function setTint(win, color, opacity) {
  const entry = attached.get(win);
  if (!entry || !api || win.isDestroyed()) return;
  api.send.ptr(entry.glass, api.sel('setTintColor:'), tintColor(color));
  api.send.double(entry.glass, api.sel('setAlphaValue:'), glassAlpha(opacity));
  keepTint(entry.glass);
}

/** Take the glass away again (the look was switched off). */
function detach(win) {
  const entry = attached.get(win);
  if (!entry || !api) return;
  attached.delete(win);
  if (win.isDestroyed()) return;
  for (const ev of ['show', 'ready-to-show', 'focus', 'blur']) win.removeListener(ev, entry.onKey);
  api.send.obj(entry.glass, api.sel('removeFromSuperview')); // the superview's retain was the last one
}

module.exports = { available, status, attach, detach, setTint, parseHex, glassAlpha, TINT_ALPHA };
