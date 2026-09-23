# ADR 0003 — Distributing Local Agent Society as a standalone app

## Status

Proposed (2026-09-23). Phase 0 applied in the same change that introduced this
ADR; phases 1–3 are the plan, not done work.

## Context

Today the system only runs on the machine of whoever develops it. A second
person on a fresh Mac cannot "open the app": there is no app to open. What
exists is a developer checkout that happens to launch things.

What a newcomer would have to do today, step by step:

1. Install Homebrew, Python 3.10+, Node 18+, `pipx`, iTerm2, and Claude Code.
2. `git clone` this repo **and** have the sibling `vortexia` repo end up at
   exactly `../vortexia` (install.sh clones it there; the widget's
   `package.json` depends on it by relative path).
3. Run `./install.sh`, which compiles an **unsigned** Electron `.app` into
   `widget-electron/dist/` (electron-builder `identity: null`, `--dir` target,
   no DMG), creates a venv, copies skills into `~/.claude/skills`, edits
   `~/.claude/settings.json`, and writes two launchd plists whose
   `ProgramArguments` are absolute paths **into the checkout**.
4. Until this ADR's Phase 0, download the 340MB Kokoro model by hand from a
   URL that only existed in a code comment — otherwise no agent has a voice.
5. The `las` CLI is a `pipx install -e` **editable** install: it is the
   checkout, not a copy of it. Move or delete the folder and everything dies.
6. On the first reboot both launchd jobs race: vortexia falls back to port
   1883 when the :8700 registry is not up yet, the registry keeps a stale
   claim, and inter-agent messaging is silently dead (found and fixed on the
   LAS side 2026-09-23, `resolve_mqtt_port` in `backend/vortexia_client.py`).

Every one of those is fine for the author and a blocker for anyone else.

## Decision

Turn the project into one installable macOS application, **"Local Agent
Society.app"**, that a user drags to `/Applications` and double-clicks, and
that owns the whole runtime: backend, broker, models, CLI, login item. The
git checkout becomes what it should be — the source, not the install.

The architecture that gets us there with the least rewriting:

```
Local Agent Society.app
├── Electron main process          ← widget windows, tray, login item, updater
│   ├── vortexia broker (aedes)    ← already Node: run in-process, no sibling repo
│   └── spawns backend sidecar     ← Python frozen with PyInstaller, in Resources/
├── Resources/las                  ← CLI binary; "Install command line tool" symlinks it
├── Resources/skills/              ← copied to ~/.claude/skills on first run / update
└── ~/Library/Application Support/Local Agent Society/
    ├── registry.json, ports.json, queue.json, attribution.json
    ├── models/kokoro/, models/whisper/     ← downloaded on first launch, with a progress UI
    └── logs/
```

Key choices, and why:

- **Keep the backend in Python, ship it frozen.** Kokoro-82M with Spanish
  voices only works through `kokoro-onnx` + native espeak-ng in Python
  (the Node route was tried and crashes on `es` voices — see the Kokoro
  commit message). PyInstaller gives one self-contained `backend` binary
  the Electron process can spawn; the app grows by a few hundred MB, which
  is acceptable for a desktop app that already needs a 340MB model.
- **Run the broker inside the Electron main process.** vortexia is Node
  and Electron already imports its client. Bundling it as an npm
  dependency (published, or a git URL) removes the `../vortexia` sibling
  requirement and the boot race with it: one process starts the registry
  first, then the broker.
- **Data lives in Application Support, not the repo.** `backend/data/`
  moves out of the checkout; a `LAS_DATA_DIR` env var overrides it so
  tests and developers keep the current layout.
- **Login item instead of launchd plists.** `app.setLoginItemSettings`
  replaces `com.localagent.system` and `com.localagentsociety.vortexia`.
  Crash supervision moves to the Electron main process (respawn the sidecar).
- **Signed and notarized.** Without a Developer ID, Gatekeeper refuses the
  app on every other Mac ("damaged, move to Trash"). This requires an Apple
  Developer account (US$99/yr) and is non-negotiable for the goal.
- **Updates through GitHub Releases** with `electron-updater`; the CLI and
  skills update with the app, so `update.sh`'s `git pull` goes away.

## Phases

**Phase 0 — make the checkout portable (done with this ADR)**
- `widget-electron/package.json`: `file:/Users/<home>/…/vortexia` → `file:../../vortexia`.
- `install.sh` downloads the Kokoro model instead of a comment telling you to.
- `resolve_mqtt_port`: backend and CLI read the broker's own
  `vortexia.port.json` before trusting the registry (the boot race).
- README/PLUGIN requirements say Node and iTerm2, not Swift.

**Phase 1 — self-contained bundle, still unsigned (developer testable)**
- Freeze the backend with PyInstaller; Electron spawns it and passes the
  data dir. Backend accepts `LAS_DATA_DIR`.
- Vendor vortexia as a real npm dependency; start the broker from main.js
  after the backend reports ready. Delete the launchd plist generation.
- First-launch model download with progress in the widget.
- Ship `las` (PyInstaller too, or a thin shell wrapper hitting :8700) inside
  `Resources/` with a menu action that symlinks it to `/usr/local/bin/las`.
- `.las-agent.json` discovery and skills install become app features.
- Definition of done: on a clean macOS user account with **nothing** but
  Claude Code installed, copying the `.app` and opening it yields a working
  widget, voice, dictation, and `las status`.

**Phase 2 — distributable**
- Developer ID signing + notarization in `electron-builder` config; `dmg`
  target; hardened runtime entitlements for microphone.
- GitHub Releases + `electron-updater`. Version the app, not the repo.
- Remove `install.sh`/`update.sh`/`uninstall.sh` from the user path (keep
  a `make dev` for contributors).

**Phase 3 — other platforms**
- Everything in `docs/WINDOWS.md`: replace the iTerm2/AppleScript paths in
  `backend/main.py` (focus, inject fallback, open terminal) with a terminal
  abstraction; Windows Terminal / Linux equivalents. The Electron shell and
  the broker are already portable; the Python sidecar freezes per platform.

## Consequences

- One repo to ship; vortexia stays a separate project but is consumed as a
  dependency, the way any other library is.
- Two build artifacts per release (Electron app + frozen backend) and a
  signing secret in CI. More release engineering than today, which is zero.
- Developers keep the current fast loop (`las start` from the checkout)
  through `LAS_DATA_DIR` and an unsigned `--dir` build; nothing in Phase 1
  removes that.
- Until Phase 2 ships, honest answer to "can someone else run this?": only
  a developer, following the README, on a Mac with the same tools installed.
