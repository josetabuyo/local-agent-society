'use strict';

/**
 * macOS Space (virtual desktop) read/move for OUR OWN BrowserWindows only.
 *
 * There is no supported Electron/AppKit API for "which Space is this window
 * on" or "move this window to Space N" — see the reasoning in the widget
 * task history. This uses the same private CGS (CoreGraphics Services)
 * calls that window-management tools like yabai/Rectangle rely on:
 *   CGSMainConnectionID, CGSCopySpacesForWindows, CGSMoveWindowsToManagedSpace
 * loaded via koffi (an N-API FFI library — no native addon build step, no
 * node-gyp/electron-rebuild, works across Electron's bundled Node ABI).
 *
 * Verified live (spike, see task history) two important, distinct things:
 *   - Moving ANOTHER process's window (e.g. iTerm2) from an external script
 *     is refused by macOS — confirmed it silently no-ops.
 *   - Moving a window OWNED BY THIS SAME PROCESS (an Electron BrowserWindow,
 *     from within the Electron main/browser process) DOES work.
 * This module is only ever used on this app's own windows for exactly that
 * reason — it must never be pointed at another process's window (e.g. the
 * agent's linked iTerm2 terminal), which both wouldn't work and isn't the
 * point: only the widget's own position/Space should be restored, nothing
 * about the agent's terminal.
 *
 * macOS-only, fails soft everywhere: any error (wrong macOS version renamed
 * a symbol, sandboxed context, etc.) just means space memory silently
 * doesn't work, never a crash or a thrown error the caller has to handle.
 */

const supported = process.platform === 'darwin';

let cf = null;
let sl = null;
let fns = null;
let cid = null;
let initError = null;

function init() {
  if (fns || initError) return;
  try {
    cf = require('koffi').load('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation');
    sl = require('koffi').load('/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight');

    const CFNumberCreate = cf.func('void* CFNumberCreate(void*, int, void*)');
    const CFArrayCreate = cf.func('void* CFArrayCreate(void*, void**, long, void*)');
    const CFArrayGetCount = cf.func('long CFArrayGetCount(void*)');
    const CFArrayGetValueAtIndex = cf.func('void* CFArrayGetValueAtIndex(void*, long)');
    const CFNumberGetValue = cf.func('unsigned char CFNumberGetValue(void*, int, void*)');

    const CGSMainConnectionID = sl.func('unsigned int CGSMainConnectionID()');
    const CGSCopySpacesForWindows = sl.func('void* CGSCopySpacesForWindows(unsigned int, int, void*)');
    const CGSMoveWindowsToManagedSpace = sl.func('void CGSMoveWindowsToManagedSpace(unsigned int, void*, unsigned long long)');

    fns = {
      CFNumberCreate,
      CFArrayCreate,
      CFArrayGetCount,
      CFArrayGetValueAtIndex,
      CFNumberGetValue,
      CGSCopySpacesForWindows,
      CGSMoveWindowsToManagedSpace,
    };
    cid = CGSMainConnectionID();
  } catch (err) {
    initError = err;
    console.warn('[widget] spaces: init failed, window-Space memory disabled:', err);
  }
}

const kCFNumberSInt32Type = 3;
const kCFNumberSInt64Type = 4;
const kCGSAllSpacesMask = 7;

function makeSingleWindowIdArray(koffi, windowId) {
  const buf = Buffer.alloc(4);
  buf.writeInt32LE(windowId, 0);
  const num = fns.CFNumberCreate(null, kCFNumberSInt32Type, buf);
  const ptrBuf = koffi.alloc('void*', 1);
  koffi.encode(ptrBuf, 'void*', num);
  return fns.CFArrayCreate(null, ptrBuf, 1, null);
}

/**
 * @param {import('electron').BrowserWindow} win
 * @returns {number|null} the CGWindowID electron assigned this window, or
 *   null if it can't be determined (window destroyed, non-macOS, etc).
 */
function cgWindowId(win) {
  if (!supported || !win || win.isDestroyed()) return null;
  try {
    // getMediaSourceId() encodes "window:<CGWindowID>:0" on macOS — the only
    // public Electron API that exposes the underlying CGWindowID.
    const match = /^window:(\d+):/.exec(win.getMediaSourceId());
    return match ? parseInt(match[1], 10) : null;
  } catch {
    return null;
  }
}

/**
 * Reads the macOS Space id64 this window currently sits on.
 * @param {import('electron').BrowserWindow} win
 * @returns {bigint|null}
 */
function getSpaceForWindow(win) {
  if (!supported) return null;
  init();
  if (!fns) return null;
  const wid = cgWindowId(win);
  if (wid == null) return null;
  try {
    const koffi = require('koffi');
    const arr = makeSingleWindowIdArray(koffi, wid);
    const spacesRet = fns.CGSCopySpacesForWindows(cid, kCGSAllSpacesMask, arr);
    if (!spacesRet) return null;
    const count = fns.CFArrayGetCount(spacesRet);
    if (count < 1) return null;
    const numPtr = fns.CFArrayGetValueAtIndex(spacesRet, 0);
    const out = Buffer.alloc(8);
    fns.CFNumberGetValue(numPtr, kCFNumberSInt64Type, out);
    return out.readBigUInt64LE(0);
  } catch (err) {
    console.warn('[widget] spaces: getSpaceForWindow failed:', err);
    return null;
  }
}

/**
 * Moves THIS APP'S OWN window to the given macOS Space. Never call this with
 * a window/id belonging to another process — see module doc.
 * @param {import('electron').BrowserWindow} win
 * @param {bigint} spaceId
 */
function moveWindowToSpace(win, spaceId) {
  if (!supported || spaceId == null) return;
  init();
  if (!fns) return;
  const wid = cgWindowId(win);
  if (wid == null) return;
  try {
    const koffi = require('koffi');
    const arr = makeSingleWindowIdArray(koffi, wid);
    fns.CGSMoveWindowsToManagedSpace(cid, arr, spaceId);
  } catch (err) {
    console.warn('[widget] spaces: moveWindowToSpace failed:', err);
  }
}

module.exports = { supported, getSpaceForWindow, moveWindowToSpace };
