#!/usr/bin/env python3
"""
Guards against the two widget-duplication bugs fixed on 2026-06-18:

  Bug 1 — `las widget` only focused existing window instead of moving it to
           the current Space.  Fix: pass ?action=reopen in the URL scheme.

  Bug 2 — Two tray binaries (tray.app + Local Agent Society.app) ran
           simultaneously, each opening its own set of widget windows on
           different Spaces.  Fix: spawnWidget guards against duplicates;
           start.sh must only launch the canonical app.

These are static source-inspection tests — no running backend needed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PASS = 0
FAIL = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"  PASS  {name}")


def fail(name: str, reason: str):
    global FAIL
    FAIL += 1
    print(f"  FAIL  {name}: {reason}")


# ── helpers ───────────────────────────────────────────────────────────────────

def _swift_src() -> str:
    return (ROOT / "widget" / "tray.swift").read_text(encoding="utf-8")


def _cli_src() -> str:
    return (ROOT / "cli" / "commands" / "agents.py").read_text(encoding="utf-8")


def _start_sh() -> str:
    return (ROOT / "start.sh").read_text(encoding="utf-8")


def _extract_func(src: str, func_name: str) -> str:
    start = src.find(func_name)
    if start == -1:
        return ""
    depth = 0
    for i, ch in enumerate(src[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return ""


# ── Bug 1: las widget must use ?action=reopen ─────────────────────────────────

def test_widget_cli_uses_action_reopen():
    """The widget command must send ?action=reopen so the tray closes the existing
    window and reopens it on the active Space instead of just focusing it."""
    src = _cli_src()
    widget_cmd_pos = src.find("@click.command(\"widget\")")
    if widget_cmd_pos == -1:
        fail("widget CLI uses ?action=reopen", "could not find @click.command(\"widget\") in agents.py")
        return
    # Check the substring after the decorator — the function body
    after = src[widget_cmd_pos:]
    if "?action=reopen" in after[:500]:
        ok("las widget CLI passes ?action=reopen in URL scheme")
    else:
        fail("las widget CLI passes ?action=reopen",
             "found 'localagentsociety://{name}' without '?action=reopen' — "
             "this makes the tray just focus the existing window instead of "
             "closing and reopening it on the current Space")


def test_reopen_widget_closes_before_spawn():
    """reopenWidget must call window.close() before spawning a new window.
    Without this, the old window stays on the old Space."""
    src = _extract_func(_swift_src(), "func reopenWidget(for")
    if not src:
        fail("reopenWidget closes before respawn", "func not found in tray.swift")
        return
    close_pos = src.find("window.close()")
    spawn_pos = src.find("spawnWidget(")
    if close_pos != -1 and spawn_pos > close_pos:
        ok("reopenWidget calls window.close() before spawnWidget")
    else:
        fail("reopenWidget calls window.close() before spawnWidget",
             "close must precede spawn so the old window is removed first")


def test_open_widget_does_not_respawn_existing():
    """openWidget must bail out if the widget already exists — it must NOT call
    spawnWidget when widgets[name] is non-nil.  This is correct behaviour:
    openWidget just focuses; reopenWidget is what moves the window."""
    src = _extract_func(_swift_src(), "func openWidget(for")
    if not src:
        fail("openWidget bails when widget exists", "func not found in tray.swift")
        return
    # The function should return early when widget exists, before calling spawnWidget
    return_pos = src.find("return")
    spawn_pos = src.find("spawnWidget(")
    if return_pos != -1 and (spawn_pos == -1 or return_pos < spawn_pos):
        ok("openWidget returns early when widget already exists (no duplicate spawn)")
    else:
        fail("openWidget returns early when widget already exists",
             "openWidget must return when widgets[name] exists, not call spawnWidget again")


# ── Bug 2: spawnWidget deduplication guard ───────────────────────────────────

def test_spawn_widget_guards_duplicates():
    """spawnWidget must guard against creating a second window for the same agent.
    Without this guard, two tray processes opening the same agent = two windows."""
    src = _extract_func(_swift_src(), "func spawnWidget(agentName:")
    if not src:
        fail("spawnWidget guards against duplicates", "func not found in tray.swift")
        return
    if "widgets[agentName] == nil" in src:
        ok("spawnWidget guards: guard widgets[agentName] == nil")
    else:
        fail("spawnWidget guards against duplicates",
             "must have 'guard widgets[agentName] == nil' to prevent "
             "two windows when more than one tray process is running")


# ── Bug 2: start.sh uses canonical app ───────────────────────────────────────

def test_start_sh_launches_canonical_app():
    """start.sh must launch 'Local Agent Society.app', not 'tray.app'.
    tray.app is a build artifact; running it alongside the canonical app
    causes every agent widget to open twice on different Spaces."""
    src = _start_sh()
    if "Local Agent Society.app" in src:
        ok("start.sh launches 'Local Agent Society.app' (canonical)")
    else:
        fail("start.sh launches canonical app",
             "start.sh must open 'Local Agent Society.app', not tray.app")


def test_start_sh_checks_for_existing_tray():
    """start.sh must pgrep for an existing tray process before launching.
    Skipping this check allows multiple tray instances to coexist."""
    src = _start_sh()
    if "pgrep" in src and "tray" in src:
        ok("start.sh checks for existing tray process before launching")
    else:
        fail("start.sh checks for existing tray process",
             "start.sh must pgrep for 'tray' and skip launch if already running")


# ── URL scheme routing ────────────────────────────────────────────────────────

def test_url_scheme_routes_reopen_to_reopen_widget():
    """The URL scheme handler must route action=reopen to reopenWidget, not openWidget.
    Routing it to openWidget would silently make ?action=reopen a no-op."""
    src = _swift_src()
    handler_start = src.find("func application(_ application: NSApplication, open urls")
    if handler_start == -1:
        fail("URL scheme routes action=reopen correctly", "URL handler not found")
        return
    handler_src = src[handler_start : handler_start + 600]
    if 'action == "reopen"' in handler_src and "reopenWidget" in handler_src:
        ok('URL scheme handler routes action="reopen" → reopenWidget')
    else:
        fail('URL scheme routes action="reopen" → reopenWidget',
             'handler must check action == "reopen" and call reopenWidget')


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Widget Reopen / Deduplication Tests ===\n")

    print("-- Bug 1: las widget must close + reopen on current Space --")
    test_widget_cli_uses_action_reopen()
    test_reopen_widget_closes_before_spawn()
    test_open_widget_does_not_respawn_existing()
    test_url_scheme_routes_reopen_to_reopen_widget()

    print("\n-- Bug 2: only one tray process, no duplicate windows --")
    test_spawn_widget_guards_duplicates()
    test_start_sh_launches_canonical_app()
    test_start_sh_checks_for_existing_tray()

    print(f"\n══════════════════════════════════")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"══════════════════════════════════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
