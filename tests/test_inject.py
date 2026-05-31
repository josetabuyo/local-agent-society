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


def first_agent() -> tuple[str, dict]:
    agents = get("/agents")
    if not agents:
        print("FAIL  no agents registered — cannot run tests")
        sys.exit(1)
    family, info = next(iter(agents.items()))
    return family, info


# ── tests ─────────────────────────────────────────────────────────────────────

def test_unknown_family_returns_404():
    status, _ = post("/agents/__nonexistent_family__/inject", {"message": "test"})
    if status == 404:
        ok("unknown family → 404")
    else:
        fail("unknown family → 404", f"got {status}")


def test_inject_writes_to_inbox():
    family, info = first_agent()
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

    inbox.write_text(before)


def test_inject_response_shape():
    family, _ = first_agent()
    status, body = post(f"/agents/{family}/inject", {"message": "shape test"})
    if status != 200:
        fail("response shape", f"HTTP {status}")
        return

    for key in ("ok", "injected", "inbox", "tty"):
        if key not in body:
            fail("response shape", f"missing field '{key}'")
            return
    ok("response contains ok, injected, inbox, tty")

    family, info = first_agent()
    inbox = Path(info.get("path", "")) / "session" / "extern-inbox.md"
    if inbox.exists():
        inbox.write_text(inbox.read_text().replace("\nshape test\n", ""))


def test_voice_source_adds_prefix():
    family, info = first_agent()
    inbox = Path(info.get("path", "")) / "session" / "extern-inbox.md"
    before = inbox.read_text() if inbox.exists() else ""

    marker = "__voice_prefix_test__"
    status, body = post(f"/agents/{family}/inject", {"message": marker, "source": "voice"})
    if status != 200:
        fail("voice prefix", f"HTTP {status}")
        return

    after = inbox.read_text() if inbox.exists() else ""
    if "[Voz]" in after and marker in after:
        ok("voice source adds [Voz] prefix to inbox")
    else:
        fail("voice source adds [Voz] prefix to inbox", f"inbox content: {repr(after[-200:])}")

    inbox.write_text(before)


def test_agent_source_adds_family_prefix():
    family, info = first_agent()
    inbox = Path(info.get("path", "")) / "session" / "extern-inbox.md"
    before = inbox.read_text() if inbox.exists() else ""

    marker = "__agent_prefix_test__"
    status, body = post(
        f"/agents/{family}/inject",
        {"message": marker, "source": "agent", "from_family": "TestBot"},
    )
    if status != 200:
        fail("agent prefix", f"HTTP {status}")
        return

    after = inbox.read_text() if inbox.exists() else ""
    if "TestBot" in after and marker in after:
        ok("agent source adds from_family prefix to inbox")
    else:
        fail("agent source adds from_family prefix to inbox", f"inbox content: {repr(after[-200:])}")

    inbox.write_text(before)


def test_inbox_entry_has_timestamp():
    family, info = first_agent()
    inbox = Path(info.get("path", "")) / "session" / "extern-inbox.md"
    before = inbox.read_text() if inbox.exists() else ""

    marker = "__timestamp_test__"
    post(f"/agents/{family}/inject", {"message": marker})

    after = inbox.read_text() if inbox.exists() else ""
    import re
    if re.search(r'\[\d{2}:\d{2} \|', after):
        ok("inbox entry includes HH:MM timestamp")
    else:
        fail("inbox entry includes HH:MM timestamp", f"no timestamp found in: {repr(after[-200:])}")

    inbox.write_text(before)


def test_newlines_in_message_dont_crash():
    family, _ = first_agent()
    status, _ = post(f"/agents/{family}/inject", {"message": "line1\nline2\r\nline3"})
    if status in (200, 422):
        ok("newlines in message don't cause 500")
    else:
        fail("newlines in message don't cause 500", f"HTTP {status}")

    family, info = first_agent()
    inbox = Path(info.get("path", "")) / "session" / "extern-inbox.md"
    if inbox.exists():
        inbox.write_text(inbox.read_text().replace("line1 line2  line3", ""))


def test_empty_message_accepted():
    family, _ = first_agent()
    status, _ = post(f"/agents/{family}/inject", {"message": ""})
    if status == 200:
        ok("empty message accepted without error")
    else:
        fail("empty message accepted without error", f"HTTP {status}")


def test_applescript_uses_ascii_return():
    """Verify _inject_via_iterm builds AppleScript with explicit carriage return."""
    import importlib.util, inspect
    main_py = Path(__file__).parent.parent / "backend" / "main.py"
    spec = importlib.util.spec_from_file_location("main", main_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod._inject_via_iterm)
    if "ASCII character 13" in src:
        ok("_inject_via_iterm uses (ASCII character 13) for Enter")
    else:
        fail("_inject_via_iterm uses (ASCII character 13) for Enter",
             "write text does not append explicit carriage return — Enter won't be sent")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Inject Endpoint Tests ===\n")
    get("/health")

    test_unknown_family_returns_404()
    test_inject_writes_to_inbox()
    test_inject_response_shape()
    test_voice_source_adds_prefix()
    test_agent_source_adds_family_prefix()
    test_inbox_entry_has_timestamp()
    test_newlines_in_message_dont_crash()
    test_empty_message_accepted()
    test_applescript_uses_ascii_return()

    print(f"\n══════════════════════════════════")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"══════════════════════════════════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
