# Windows port — plan

Rewritten 2026-11-27. Goal: a Windows PC runs LAS with everything a Mac has.
That means a Claude Code session in a LAS agent, its widget, its voice and its
mic, and live messaging with agents on other machines. The first real user is
a friend's PC (Joel), whose agent will work daily with an agent on ba-mac. A
second Windows PC on ba-mac's LAN is the test bench.

The 2026-08-31 punch list this replaces predates Kokoro, the bridge, sessions
and the relay. Its findings are folded in below.

## Where things stand

- **Already portable:**
  - Vortexia: Node, aedes and MQTT.
  - The relay: Nostr over WebSocket.
  - The bridge: Node. `quoteArg` and the exec sink already branch on `win32`.
  - Electron itself.
  - Kokoro: onnxruntime and espeak-ng both ship Windows wheels.
  - Whisper: transformers.js in the renderer.
  - `cli/connected.py`: its detach logic already has a `win32` branch.
- **macOS only:**
  - Services: launchd plists and `backend/service.sh`.
  - Every `*.sh`: install, update, start, stop, `restart-widget.sh`.
  - Terminal control: osascript with iTerm2/Ghostty for focus, beacon, inject fallback, open terminal and tty write.
  - Process lookup: `lsof`, `ps`, `pgrep`.
  - `fcntl` locks.
  - `cli/pty_session.py`: pty and termios, used by `las codex` and the PTY fallback.
  - `$SHELL -lc` in the voice-session endpoint.
  - Spaces: SkyLight FFI, which already fails soft.
  - The widget build: `--mac --dir` only.

## Steps, in order

1. **Windows CI.** `.github/workflows/windows.yml` runs the Python, bridge and widget suites on `windows-latest`. Its failures are the punch list for steps 2–5, and it is the feedback loop that works without touching a Windows PC.
2. **Test bench.** Turn on OpenSSH Server on the LAN Windows PC, so ba-mac can drive it the way it drives uy-mac. Install Git, Python 3.12, Node 22 and Claude Code there with winget.
3. **Portable core.** The CLI, backend and bridge run on Windows:
   - Paths: `~/.las` and `backend/data` through `Path.home()`.
   - Locks: `fcntl` → `msvcrt` behind one helper.
   - Processes: `lsof`/`ps` → `psutil`.
   - Login shell: `$SHELL -lc` → `powershell -NoProfile -Command`.
   - PTY: `pty_session` → ConPTY through `pywinpty`.
   - Signals: SIGHUP → process-tree kill.
4. **Services and lifecycle.** The backend and vortexia run at logon as per-user Task Scheduler tasks, replacing launchd. `las start|stop|update|restart` move from bash into Python so one implementation serves both OSes, and `service.sh` stays as the macOS backend of that code.
5. **Installer.** `install.ps1` covers prerequisites through winget, pipx, npm, the Kokoro model, skills, `~/.claude.json` MCP registration and hooks. After that, `las update` alone keeps the PC current (remote users first-class).
6. **Claude Code on Windows.**
   - `las claude` / `claudeRelay` start `claude.exe` with the channel.
   - The bridge MCP command uses `node.exe` with a Windows path.
   - Hook command strings must work from cmd/PowerShell.
   - Voice sessions (ADR 0008) and `las codex`.
7. **Terminals.** Windows Terminal (`wt.exe`) for ⧉ open, ⌖ find (window title plus `SetForegroundWindow`) and ✕ close (kill the session's process tree). Inject stays vortexia-only, with no keystroke fallback.
8. **Widget.**
   - An electron-builder `win` target (nsis or portable).
   - The `localagentsociety://` protocol registered in the registry.
   - Tray, always-on-top, mic permission and Kokoro playback.
   - Spaces stay off, and the mosaic groups per display.
9. **Two societies talking.** The bench PC's agent and a ba-mac agent exchange `Name@env` messages through the relay and friends, by voice and by text. This is the end-to-end acceptance test.
10. **Joel's install.** Run the installer on his PC, create his agent, and pair it with ba-mac's agent. Update the docs, the boarding page and the skill with a Windows section.

## Decisions taken

- One codebase, branching on `sys.platform` / `process.platform` behind small helpers. No Windows fork.
- No WSL: Claude Code, Electron and the mic all run natively. WSL would split the system in two.
- Terminal: Windows Terminal. It is the iTerm2 analog and ships with Windows 11.
- Vortexia is its own project: Windows changes there are requested from the Vortexia agent, not patched here.
