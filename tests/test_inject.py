#!/usr/bin/env python3
"""
Tests for POST /agents/{family}/inject endpoint.
Usage: python3 tests/test_inject.py
"""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path
import tempfile
import os

BACKEND = "http://localhost:8700"
PASS = 0
FAIL = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"  PASS {name}")


def fail(name: str, reason: str):
    global FAIL
    FAIL += 1
    print(f"  FAIL {name}: {reason}")


def post(path: str, body: dict, timeout: int = 5) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BACKEND}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def get(path: str, timeout: int = 3) -> dict:
    try:
        with urllib.request.urlopen(f"{BACKEND}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"FAIL  backend unreachable: {e}")
        sys.exit(1)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_unknown_family_returns_404():
    status, _ = post("/agents/__nonexistent_family__/inject", {"message": "test"})
    if status == 404:
        ok("unknown family → 404")
    else:
        fail("unknown family → 404", f"got {status}")


def test_inject_writes_to_inbox():
    agents = get("/agents")
    if not agents:
        fail("inbox write", "no agents registered")
        return

    family, info = next(iter(agents.items()))
    path = Path(info.get("path", ""))
    inbox = path / "session" / "extern-inbox.md"

    before = inbox.read_text() if inbox.exists() else ""
    marker = "__test_inject_marker__"

    status, body = post(f"/agents/{family}/inject", {"message": marker})
    if status != 200:
        fail("inbox write", f"HTTP {status}")
        return
    if not body.get("ok"):
        fail("inbox write", f"ok=false: {body}")
        return

    after = inbox.read_text() if inbox.exists() else ""
    if marker in after:
        ok("inject writes message to extern-inbox")
    else:
        fail("inject writes message to extern-inbox", "marker not found in inbox")

    # cleanup
    inbox.write_text(before)


def test_inject_response_shape():
    agents = get("/agents")
    if not agents:
        fail("response shape", "no agents registered")
        return

    family = next(iter(agents))
    status, body = post(f"/agents/{family}/inject", {"message": "shape test"})
    if status != 200:
        fail("response shape", f"HTTP {status}")
        return

    for key in ("ok", "injected", "inbox", "tty"):
        if key not in body:
            fail("response shape", f"missing field '{key}'")
            return
    ok("response contains ok, injected, inbox, tty")

    # cleanup
    path = Path(agents[family].get("path", ""))
    inbox = path / "session" / "extern-inbox.md"
    if inbox.exists():
        text = inbox.read_text()
        inbox.write_text(text.replace("\nshape test\n", ""))


def test_newlines_in_message_dont_crash():
    agents = get("/agents")
    if not agents:
        fail("newline escaping", "no agents registered")
        return
    family = next(iter(agents))
    # Should not 500 even if injection fails (iTerm may not be running in CI)
    status, body = post(f"/agents/{family}/inject", {"message": "line1\nline2\r\nline3"})
    if status in (200, 422):
        ok("newlines in message don't cause 500")
    else:
        fail("newlines in message don't cause 500", f"HTTP {status}")

    # cleanup
    path = Path(agents[family].get("path", ""))
    inbox = path / "session" / "extern-inbox.md"
    if inbox.exists():
        text = inbox.read_text()
        inbox.write_text(text.replace("\nline1\nline2\r\nline3\n", ""))


def test_empty_message_still_accepted():
    agents = get("/agents")
    if not agents:
        fail("empty message", "no agents registered")
        return
    family = next(iter(agents))
    status, _ = post(f"/agents/{family}/inject", {"message": ""})
    # Backend accepts empty strings (writes blank line to inbox, harmless)
    if status == 200:
        ok("empty message accepted without error")
    else:
        fail("empty message accepted without error", f"HTTP {status}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Inject Endpoint Tests ===\n")

    # Sanity check
    try:
        get("/health")
    except SystemExit:
        sys.exit(1)

    test_unknown_family_returns_404()
    test_inject_writes_to_inbox()
    test_inject_response_shape()
    test_newlines_in_message_dont_crash()
    test_empty_message_still_accepted()

    print(f"\n══════════════════════════════════")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"══════════════════════════════════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
