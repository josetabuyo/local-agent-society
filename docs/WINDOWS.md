# Windows support — status and what's missing

Written 2026-08-31, after the Swift → Electron widget migration. The widget
shell (`widget-electron/`) is Electron, which is cross-platform in principle,
and `main.js` already has a couple of `process.platform === 'win32'`
branches — but the system as a whole is **macOS-only today**. This is a
punch list for whoever picks up Windows support later, not a promise that
it's close.

## What already doesn't care about the OS

- Vortexia messaging (MQTT), the backend registry/ports API, dictation
  (local Whisper), and TTS playback (Web Speech API in the renderer, driven
  by a `las/speak` vortexia message — see `backend/main.py`'s `tts_drainer`)
  are all plain cross-platform code paths already. Voice *names* are
  macOS `say` voice names (Samantha, Daniel, ...); Windows would resolve
  different SAPI voices under the hood via Web Speech, so per-agent voice
  identity wouldn't carry over as-is.
- `widget-electron/main.js`'s `openTerminalAtPath()` already branches on
  `win32` (see around the `terminal:open` IPC handler) for the **command
  palette's** "open terminal" commands.

## What is 100% macOS/iTerm2-specific, no fallback

- `backend/main.py`: `_focus_via_iterm`, `_inject_via_iterm`, `open_terminal`,
  `write_to_tty`, `_find_all_claude_ttys`, `_run_osascript_with_argv` — every
  one of these shells out to `osascript` and iTerm2 AppleScript. This is what
  makes `las agent focus`, `las agent inject`, the widget's Clear/Focus
  buttons, and the wake-via-vortexia fallback (`las agent focus` opening a
  fresh session) actually work. None of it has a Windows equivalent.
- `widget-electron/lib/spaces.js`: macOS Space (virtual desktop) read/move,
  via private CoreGraphics/SkyLight calls (koffi FFI). Gated by
  `supported = process.platform === 'darwin'` and fails soft — on Windows,
  `getSpaceForWindow` always returns `null`, so the mosaic-tiling grouping
  (`mosaicKeyFor` in `main.js`) collapses every occluded widget on one
  physical display into a single bucket instead of grouping per virtual
  desktop. Not a crash, just not equivalent (mirrors the pre-fix bug this
  session fixed for macOS — see git history for `mosaicKeyFor`).

## Packaging/installer

- `widget-electron/package.json`'s `build` script is hardcoded
  `electron-builder --mac --dir`, and the `build` config block only has a
  `mac` target — **no `win` target is configured**, so `npm run build`
  cannot produce a Windows executable today, regardless of the app code.
- `install.sh` is bash-only, with paths hardcoded to
  `dist/mac-arm64/*.app` / `dist/mac/*.app`. No `.ps1`/`.bat` equivalent, no
  Windows install instructions anywhere.

## If someone picks this up

Recommended terminal: **Windows Terminal** (`wt.exe`) — closest analog to
iTerm2 (tabs/panes, scriptable via its own CLI, maintained by Microsoft).
Rough task list, roughly in dependency order:

1. Add a `win` target to `widget-electron/package.json`'s `build` config
   (e.g. `nsis` or `portable`) and a matching build script.
2. Port `_focus_via_iterm`/`_inject_via_iterm`/`open_terminal`/`write_to_tty`
   to a Windows Terminal equivalent (`wt.exe` supports launching/targeting
   panes; there's no AppleScript-equivalent scripting story, likely needs a
   window-title-based or `wt` process-tracking approach — needs its own
   research spike).
3. Decide what "Space-aware mosaic" should mean on Windows (Windows 10/11
   virtual desktops have no supported public API for "which desktop is this
   window on" either — likely stays best-effort/off).
4. Write a Windows installer script and matching docs section.
5. Re-verify voice mapping — Web Speech API voice availability differs
   completely on Windows (SAPI voices, not `say` voices); the per-agent
   voice catalogue (`allVoices`/`NICE_VOICES`, see the `Voice locale system`
   memory) would need a Windows-side equivalent list.
