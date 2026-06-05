#!/usr/bin/env python3
"""
Tests for POST /agents/{name}/inject endpoint.
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
    name, info = next(iter(agents.items()))
    return name, info


# ── tests ─────────────────────────────────────────────────────────────────────

def test_unknown_agent_returns_404():
    status, _ = post("/agents/__nonexistent_agent__/inject", {"message": "test"})
    if status == 404:
        ok("unknown agent → 404")
    else:
        fail("unknown agent → 404", f"got {status}")


def test_inject_response_shape():
    name, _ = first_agent()
    status, body = post(f"/agents/{name}/inject", {"message": "shape test"})
    if status != 200:
        fail("response shape", f"HTTP {status}")
        return

    for key in ("ok", "injected", "tty"):
        if key not in body:
            fail("response shape", f"missing field '{key}'")
            return
    if "inbox" in body:
        fail("response shape", "inbox field should not exist — inbox was removed")
        return
    ok("response contains ok, injected, tty (no inbox)")


def test_voice_source_returns_ok():
    name, _ = first_agent()
    marker = "__voice_prefix_test__"
    status, body = post(f"/agents/{name}/inject", {"message": marker, "source": "voice"})
    if status == 200 and body.get("ok"):
        ok("voice source inject returns ok=true")
    else:
        fail("voice source inject returns ok=true", f"HTTP {status} body={body}")


def test_agent_source_returns_ok():
    name, _ = first_agent()
    marker = "__agent_prefix_test__"
    status, body = post(
        f"/agents/{name}/inject",
        {"message": marker, "source": "agent", "from_agent": "TestBot"},
    )
    if status == 200 and body.get("ok"):
        ok("agent source inject returns ok=true")
    else:
        fail("agent source inject returns ok=true", f"HTTP {status} body={body}")


def test_newlines_in_message_dont_crash():
    name, _ = first_agent()
    status, _ = post(f"/agents/{name}/inject", {"message": "line1\nline2\r\nline3"})
    if status in (200, 422):
        ok("newlines in message don't cause 500")
    else:
        fail("newlines in message don't cause 500", f"HTTP {status}")



def test_empty_message_accepted():
    name, _ = first_agent()
    status, _ = post(f"/agents/{name}/inject", {"message": ""})
    if status == 200:
        ok("empty message accepted without error")
    else:
        fail("empty message accepted without error", f"HTTP {status}")


def test_raw_source_no_prefix():
    """Verify source=raw injects the message as-is with no prefix."""
    name, info = first_agent()
    marker = "__raw_prefix_test__"

    log_path = Path(info["path"]) / "session" / "inject.log"
    before_size = log_path.stat().st_size if log_path.exists() else 0

    status, body = post(f"/agents/{name}/inject", {"message": marker, "source": "raw"})
    if not (status == 200 and body.get("ok")):
        fail("raw source inject returns ok=true", f"HTTP {status} body={body}")
        return
    ok("raw source inject returns ok=true")

    # Read only the new lines written after the request
    if log_path.exists():
        with open(log_path) as f:
            f.seek(before_size)
            new_lines = f.read()
        if f"msg='{marker}'" in new_lines and f"source=raw" in new_lines:
            ok("inject.log confirms message injected without prefix")
        elif marker in new_lines and "[External]" not in new_lines and "[Widget" not in new_lines:
            ok("inject.log confirms message injected without prefix")
        else:
            fail("inject.log confirms message injected without prefix",
                 f"new log lines: {new_lines!r}")
    else:
        fail("inject.log confirms message injected without prefix", "log file not found")


def test_inject_sends_return_via_iterm():
    """Verify _inject_via_iterm sends Enter within the iTerm2 tell block (not via System Events)."""
    import importlib.util, inspect
    main_py = Path(__file__).parent.parent / "backend" / "main.py"
    spec = importlib.util.spec_from_file_location("main", main_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod._inject_via_iterm)
    if "ASCII character 13" in src and "System Events" not in src:
        ok("_inject_via_iterm sends Enter via ASCII character 13 within iTerm2 tell block")
    else:
        fail("_inject_via_iterm sends Enter via ASCII character 13 within iTerm2 tell block",
             "Expected ASCII character 13 inside iTerm2 tell block — no System Events")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Inject Endpoint Tests ===\n")
    get("/health")

    test_unknown_agent_returns_404()
    test_inject_response_shape()
    test_voice_source_returns_ok()
    test_agent_source_returns_ok()
    test_newlines_in_message_dont_crash()
    test_empty_message_accepted()
    test_raw_source_no_prefix()
    test_inject_sends_return_via_iterm()

    print(f"\n══════════════════════════════════")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"══════════════════════════════════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
