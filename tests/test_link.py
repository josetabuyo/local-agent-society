#!/usr/bin/env python3
"""
Guards for the drag-to-link feature (scope button → las link) and the
las widgets command added in the 2026-06-30 session.

Design invariants being tested:
  - las link: CLI command registered; TTY detection walks the process tree
  - las widgets: registered; reopens all agents with ?action=reopen
  - Drag payload: no '!' prefix (breaks bash history); Enter via AppleScript
  - Backend: /pin-tty and /pending-link endpoints; pending-link consumed once

All tests are static source-inspection — no running backend needed.
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


def _swift_src() -> str:
    return (ROOT / "widget" / "tray.swift").read_text(encoding="utf-8")


def _cli_src() -> str:
    return (ROOT / "cli" / "commands" / "agents.py").read_text(encoding="utf-8")


def _main_py() -> str:
    return (ROOT / "cli" / "main.py").read_text(encoding="utf-8")


def _backend_src() -> str:
    return (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def _extract_func_swift(src: str, func_name: str) -> str:
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
                return src[start: i + 1]
    return ""


# ── CLI registration ──────────────────────────────────────────────────────────

def test_link_command_registered():
    """cli/main.py must import link and widgets_all and register them as CLI commands."""
    src = _main_py()
    if "widgets_all" in src and "link" in src and 'name="widgets"' in src:
        ok("cli/main.py registers link and widgets commands")
    else:
        fail("cli/main.py registers link and widgets",
             "missing import or add_command for 'link' / 'widgets_all' in cli/main.py")


# ── las widgets ───────────────────────────────────────────────────────────────

def test_widgets_command_fetches_all_agents():
    """widgets_all must call api.get('/agents') and iterate over every registered agent name."""
    src = _cli_src()
    start = src.find("def widgets_all(")
    if start == -1:
        fail("widgets_all fetches all agents", "def widgets_all not found in agents.py")
        return
    body = src[start: start + 600]
    if 'api.get("/agents")' in body and "for name in" in body:
        ok("widgets_all calls api.get('/agents') and iterates all names")
    else:
        fail("widgets_all fetches all agents",
             "must call api.get('/agents') and iterate names")


def test_widgets_command_uses_action_reopen():
    """widgets_all must pass ?action=reopen in the URL so each widget moves to the current Space."""
    src = _cli_src()
    start = src.find("def widgets_all(")
    if start == -1:
        fail("widgets_all uses ?action=reopen", "def widgets_all not found")
        return
    body = src[start: start + 600]
    if "?action=reopen" in body:
        ok("widgets_all uses ?action=reopen in URL scheme (same as las widget)")
    else:
        fail("widgets_all uses ?action=reopen",
             "must pass '?action=reopen' to localagentsociety:// URL so windows move to the current Space")


# ── Drag payload ──────────────────────────────────────────────────────────────

def test_drag_payload_no_exclamation():
    """ScopeDragButton drag payload must use 'las link --agent' without a '!' prefix.
    The '!' prefix is Claude Code-specific; in regular bash/zsh shells it triggers
    history expansion and causes 'event not found' errors."""
    src = _extract_func_swift(_swift_src(), "override func mouseDragged")
    if not src:
        fail("drag payload has no '!' prefix", "mouseDragged func not found in tray.swift")
        return
    if "las link --agent" in src and '!"las link' not in src and '"!las link' not in src:
        ok("drag payload uses 'las link --agent' without '!' prefix")
    else:
        fail("drag payload has no '!' prefix",
             "pasteboard string must be 'las link --agent NAME' — '!' breaks bash/zsh history expansion")


def test_drag_payload_no_trailing_newline_in_pasteboard():
    """The pasteboard string must NOT end with \\n.
    Enter is sent separately via AppleScript after the text is pasted,
    matching the same two-step mechanism used by _inject_via_iterm."""
    src = _extract_func_swift(_swift_src(), "override func mouseDragged")
    if not src:
        fail("drag payload has no trailing newline", "mouseDragged func not found")
        return
    # The setString call must not have \n at the end of the string literal
    if 'las link --agent' in src and '\\n"' not in src and r'\n"' not in src:
        ok("drag pasteboard string has no trailing \\n (Enter sent via separate AppleScript call)")
    else:
        fail("drag payload has no trailing newline in pasteboard",
             "must not embed \\n in the pasteboard string — send Enter via AppleScript instead")


def test_drag_sends_enter_via_applescript():
    """sendEnterToFrontmostITerm must use 'ASCII character 13' inside an iTerm2 tell block.
    This is the same mechanism as _inject_via_iterm — sends Enter at the PTY level."""
    src = _extract_func_swift(_swift_src(), "func sendEnterToFrontmostITerm")
    if not src:
        fail("drag sends Enter via AppleScript", "sendEnterToFrontmostITerm not found in tray.swift")
        return
    if "ASCII character 13" in src and "iTerm2" in src:
        ok("sendEnterToFrontmostITerm uses 'ASCII character 13' inside iTerm2 tell block")
    else:
        fail("drag sends Enter via AppleScript",
             "must use 'ASCII character 13' inside 'tell application \"iTerm2\"' block")


# ── Backend endpoints ─────────────────────────────────────────────────────────

def test_pin_tty_endpoint_exists():
    """backend/main.py must define POST /agents/{name}/pin-tty to register a pending TTY link."""
    src = _backend_src()
    if "/agents/{name}/pin-tty" in src and "@app.post" in src:
        ok("POST /agents/{name}/pin-tty endpoint defined in backend")
    else:
        fail("POST /agents/{name}/pin-tty exists",
             "backend/main.py must define @app.post('/agents/{name}/pin-tty')")


def test_pending_link_endpoint_exists():
    """backend/main.py must define GET /agents/{name}/pending-link to let the widget poll for a linked TTY."""
    src = _backend_src()
    if "/agents/{name}/pending-link" in src and "@app.get" in src:
        ok("GET /agents/{name}/pending-link endpoint defined in backend")
    else:
        fail("GET /agents/{name}/pending-link exists",
             "backend/main.py must define @app.get('/agents/{name}/pending-link')")


def test_pending_link_pops_and_clears():
    """The pending-link GET handler must use .pop() to consume and clear the entry.
    Using .get() would leave the value in place and allow the widget to link
    to the same TTY repeatedly across multiple polls."""
    src = _backend_src()
    start = src.find("/agents/{name}/pending-link")
    if start == -1:
        fail("pending-link uses .pop()", "/agents/{name}/pending-link not found in backend")
        return
    body = src[start: start + 400]
    if ".pop(" in body:
        ok("pending-link endpoint uses .pop() — consumed exactly once")
    else:
        fail("pending-link uses .pop()",
             "must use _pending_links.pop(name, None) so the TTY is consumed once and not re-delivered")


# ── las link TTY detection ────────────────────────────────────────────────────

def test_las_link_tty_walks_process_tree():
    """las link must walk the process tree via 'ps -p' to find a TTY.
    Walking up the tree is required when las link is run via '!' inside Claude
    Code, where stdin is a pipe (not a TTY) but an ancestor process owns the
    controlling terminal."""
    src = _cli_src()
    start = src.find("def link(")
    if start == -1:
        fail("las link walks process tree for TTY", "def link not found in agents.py")
        return
    body = src[start: start + 800]
    if 'ps' in body and '-p' in body and 'getpid' in body:
        ok("las link walks process tree via 'ps -p' to find controlling TTY")
    else:
        fail("las link walks process tree for TTY",
             "must use subprocess.run(['ps', '-p', str(pid), '-o', 'tty=,ppid=']) "
             "and walk ancestors until a non-?? TTY is found")


def test_las_link_accepts_tty_override():
    """las link must accept a --tty option to allow explicit TTY specification.
    Useful when auto-detection fails or when scripting the link programmatically."""
    src = _cli_src()
    if '--tty' in src and 'tty_override' in src:
        ok("las link accepts --tty override option")
    else:
        fail("las link accepts --tty override",
             "must have @click.option('--tty', 'tty_override', ...) in the link command")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Link / Drag-to-Terminal Tests ===\n")

    print("-- CLI registration --")
    test_link_command_registered()

    print("\n-- las widgets --")
    test_widgets_command_fetches_all_agents()
    test_widgets_command_uses_action_reopen()

    print("\n-- Drag payload --")
    test_drag_payload_no_exclamation()
    test_drag_payload_no_trailing_newline_in_pasteboard()
    test_drag_sends_enter_via_applescript()

    print("\n-- Backend endpoints --")
    test_pin_tty_endpoint_exists()
    test_pending_link_endpoint_exists()
    test_pending_link_pops_and_clears()

    print("\n-- las link TTY detection --")
    test_las_link_tty_walks_process_tree()
    test_las_link_accepts_tty_override()

    print(f"\n══════════════════════════════════")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"══════════════════════════════════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
