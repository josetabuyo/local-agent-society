#!/usr/bin/env python3
"""
Tests for the agent focus / TTY lookup system.

Covers:
  - GET /agents/{name}/ttys endpoint shape and contract
  - focusSession AppleScript in tray.swift (static source inspection)

Usage: python3 tests/test_focus.py
"""
import importlib.util
import inspect
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = "http://localhost:8700"
PASS = 0
FAIL = 0

ROOT = Path(__file__).parent.parent


def ok(name: str):
    global PASS
    PASS += 1
    print(f"  PASS {name}")


def fail(name: str, reason: str):
    global FAIL
    FAIL += 1
    print(f"  FAIL {name}: {reason}")


def get(path: str, timeout: int = 5) -> tuple[int, dict | list]:
    try:
        with urllib.request.urlopen(f"{BACKEND}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        print(f"FAIL  backend unreachable: {e}")
        sys.exit(1)


def first_agent() -> str:
    _, agents = get("/agents")
    if not agents:
        print("FAIL  no agents registered — cannot run tests")
        sys.exit(1)
    return next(iter(agents))


# ── endpoint tests ─────────────────────────────────────────────────────────────

def test_ttys_unknown_agent_returns_404():
    status, _ = get("/agents/__nonexistent__/ttys")
    if status == 404:
        ok("unknown agent → 404")
    else:
        fail("unknown agent → 404", f"got HTTP {status}")


def test_ttys_response_shape():
    name = first_agent()
    status, body = get(f"/agents/{name}/ttys")
    if status != 200:
        fail("ttys response shape", f"HTTP {status}")
        return
    if "ttys" not in body:
        fail("ttys response shape", "missing 'ttys' key")
        return
    if not isinstance(body["ttys"], list):
        fail("ttys response shape", f"'ttys' is {type(body['ttys']).__name__}, expected list")
        return
    ok("GET /agents/{name}/ttys returns {ttys: [...]}")


def test_ttys_values_are_strings():
    name = first_agent()
    _, body = get(f"/agents/{name}/ttys")
    ttys = body.get("ttys", [])
    bad = [t for t in ttys if not isinstance(t, str)]
    if bad:
        fail("ttys values are strings", f"non-string entries: {bad}")
    else:
        ok("all tty values are strings")


def test_ttys_no_dev_prefix():
    """TTYs from the backend should be short form (ttysNNN), not /dev/ttysNNN.
    The widget adds /dev/ itself; mixing prefixes would break the contains check."""
    name = first_agent()
    _, body = get(f"/agents/{name}/ttys")
    ttys = body.get("ttys", [])
    prefixed = [t for t in ttys if t.startswith("/")]
    if prefixed:
        fail("tty values have no /dev/ prefix", f"got prefixed entries: {prefixed}")
    else:
        ok("tty values are short form (ttysNNN, no /dev/ prefix)")


def test_ttys_no_question_marks():
    """?? means the process has no controlling terminal — should be filtered out."""
    name = first_agent()
    _, body = get(f"/agents/{name}/ttys")
    ttys = body.get("ttys", [])
    bad = [t for t in ttys if "?" in t]
    if bad:
        fail("ttys excludes ?? entries", f"got: {bad}")
    else:
        ok("ttys list excludes ?? (no-tty) entries")


def test_ttys_deduplicated():
    name = first_agent()
    _, body = get(f"/agents/{name}/ttys")
    ttys = body.get("ttys", [])
    if len(ttys) == len(set(ttys)):
        ok("ttys list has no duplicates")
    else:
        fail("ttys list has no duplicates", f"duplicates found in {ttys}")


# ── Swift source inspection ────────────────────────────────────────────────────

def _focus_session_source() -> str:
    swift = (ROOT / "widget" / "tray.swift").read_text(encoding="utf-8")
    start = swift.find("func focusSession(tty:")
    if start == -1:
        return ""
    # grab from function start to the closing brace (simple heuristic)
    depth = 0
    i = start
    for i, ch in enumerate(swift[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
    return swift[start:i + 1]


def test_focus_uses_bundle_id_not_name():
    """Use bundle ID 'com.googlecode.iterm2' — more reliable than display name."""
    src = _focus_session_source()
    if not src:
        fail("focusSession source found", "func not found in tray.swift")
        return
    if "com.googlecode.iterm2" in src:
        ok("focusSession targets iTerm2 by bundle ID")
    else:
        fail("focusSession targets iTerm2 by bundle ID",
             "should use 'application id \"com.googlecode.iterm2\"'")


def test_focus_iterates_by_index():
    """Iterate windows/tabs/sessions by numeric index so iTerm2 gets proper object refs."""
    src = _focus_session_source()
    if not src:
        return
    if "from 1 to" in src and ("count of windows" in src or "winCount" in src):
        ok("focusSession iterates by numeric index")
    else:
        fail("focusSession iterates by numeric index",
             "must use 'repeat with wi from 1 to count of windows' — "
             "'repeat with w in windows' gives non-addressable refs")


def test_focus_no_set_current_tab():
    """'set current tab of w to t' throws -10000 from NSAppleScript — must not be used."""
    src = _focus_session_source()
    if not src:
        return
    if "set current tab" in src:
        fail("focusSession omits set-current-tab", "'set current tab' throws -10000")
    else:
        ok("focusSession does not use 'set current tab' (throws -10000)")


def test_focus_try_wraps_only_tty_access():
    """The try block must wrap only 'tty of s', not the contains/activate block.
    A wider try silently swallows the iTerm error and prevents the match."""
    src = _focus_session_source()
    if not src:
        return
    # 'contains' must appear OUTSIDE a try block — i.e. after 'end try'
    end_try_pos = src.find("end try")
    contains_pos = src.find("contains")
    if end_try_pos != -1 and contains_pos > end_try_pos:
        ok("'contains' check is outside the try block")
    else:
        fail("'contains' check is outside the try block",
             "wrapping 'contains' inside try silently swallows iTerm errors")


def test_focus_uses_set_index_and_activate():
    src = _focus_session_source()
    if not src:
        return
    missing = [cmd for cmd in ("set index of w to 1", "activate") if cmd not in src]
    if missing:
        fail("focusSession uses set-index + activate", f"missing: {missing}")
    else:
        ok("focusSession uses 'set index of w to 1' + 'activate'")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Focus / TTY Tests ===\n")

    print("-- Endpoint: GET /agents/{name}/ttys --")
    test_ttys_unknown_agent_returns_404()
    test_ttys_response_shape()
    test_ttys_values_are_strings()
    test_ttys_no_dev_prefix()
    test_ttys_no_question_marks()
    test_ttys_deduplicated()

    print("\n-- Swift: focusSession AppleScript --")
    test_focus_uses_bundle_id_not_name()
    test_focus_iterates_by_index()
    test_focus_no_set_current_tab()
    test_focus_try_wraps_only_tty_access()
    test_focus_uses_set_index_and_activate()

    print(f"\n══════════════════════════════════")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"══════════════════════════════════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
