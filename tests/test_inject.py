#!/usr/bin/env python3
"""
Tests for POST /agents/{name}/inject endpoint.

Runs against a disposable, throwaway agent + terminal created just for this
test run — never against a real live agent's terminal. A fake "claude"
process (argv0 rewritten via `exec -a claude`) is launched in a brand-new
iTerm2 window backed by `cat`, which makes it indistinguishable to the
backend's process-discovery logic (ps/lsof) from a real agent session, while
just appending whatever gets injected into a local capture.log we can assert
on. The window, process, temp dir, and agent registration are all torn down
at the end (best-effort, even on failure).

Usage: python3 tests/test_inject.py
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

BACKEND = "http://localhost:8700"
PROBE_NAME = "__e2e_inject_probe__"
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


def delete(path: str, timeout: int = 5) -> int:
    req = urllib.request.Request(f"{BACKEND}{path}", method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except Exception:
        return 0


def get(path: str, timeout: int = 3) -> dict:
    try:
        with urllib.request.urlopen(f"{BACKEND}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"FAIL  backend unreachable: {e}")
        sys.exit(1)


# ── disposable probe terminal ────────────────────────────────────────────────
# A real iTerm2 window running a process that *looks* like a claude session
# (ps shows command="claude") so the backend's real discovery/injection path
# runs unmodified, but nothing it does can touch a real agent.

def _osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout.strip()


def setup_probe():
    tmp_dir = Path(tempfile.mkdtemp(prefix="e2e_inject_probe_")).resolve()
    (tmp_dir / "session").mkdir()
    (tmp_dir / ".agent.json").write_text(
        json.dumps({"name": PROBE_NAME, "voice": "Samantha", "locale": "en-US"})
    )
    launcher = tmp_dir / "run_fake_claude.sh"
    launcher.write_text(
        f'#!/bin/bash\ncd "{tmp_dir}"\nexec -a claude cat >> "{tmp_dir}/capture.log"\n'
    )
    launcher.chmod(0o755)

    window_id = int(_osascript(
        f'tell application "iTerm2"\n'
        f'    create window with default profile command "bash \\"{launcher}\\""\n'
        f'    return id of current window\n'
        f'end tell'
    ))

    # Register the probe as a temp agent and wait for the backend to discover
    # the fake claude process's tty (mirrors real agent startup timing).
    status, _ = post("/agents", {"name": PROBE_NAME, "voice": "Samantha", "path": str(tmp_dir)})
    if status != 200:
        raise RuntimeError(f"failed to register probe agent: HTTP {status}")

    pid = None
    tty = None
    for _ in range(20):
        ttys = get(f"/agents/{PROBE_NAME}/ttys").get("ttys", [])
        if ttys:
            tty = ttys[0]
            break
        time.sleep(0.25)
    if tty is None:
        raise RuntimeError("backend never discovered the probe's fake claude process")

    # Resolve the pid for cleanup (best-effort — not required for tests to run).
    ps_out = subprocess.run(["ps", "-ax", "-o", "pid=,tty=,command="], capture_output=True, text=True).stdout
    for line in ps_out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[2].strip() == "claude" and tty in parts[1]:
            pid = int(parts[0])
            break

    return {"tmp_dir": tmp_dir, "window_id": window_id, "pid": pid, "tty": tty}


def teardown_probe(ctx: dict):
    delete(f"/agents/{PROBE_NAME}")
    if ctx.get("pid"):
        try:
            os.kill(ctx["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(3):
        try:
            _osascript(f'tell application "iTerm2" to close window id {ctx["window_id"]}')
            break
        except RuntimeError:
            time.sleep(0.3)
    shutil.rmtree(ctx["tmp_dir"], ignore_errors=True)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_unknown_agent_returns_404():
    status, _ = post("/agents/__nonexistent_agent__/inject", {"message": "test"})
    if status == 404:
        ok("unknown agent → 404")
    else:
        fail("unknown agent → 404", f"got {status}")


def test_inject_response_shape():
    status, body = post(f"/agents/{PROBE_NAME}/inject", {"message": "shape test"})
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
    marker = "__voice_prefix_test__"
    status, body = post(f"/agents/{PROBE_NAME}/inject", {"message": marker, "source": "voice"})
    if status == 200 and body.get("ok"):
        ok("voice source inject returns ok=true")
    else:
        fail("voice source inject returns ok=true", f"HTTP {status} body={body}")


def test_agent_source_returns_ok():
    marker = "__agent_prefix_test__"
    status, body = post(
        f"/agents/{PROBE_NAME}/inject",
        {"message": marker, "source": "agent", "from_agent": "TestBot"},
    )
    if status == 200 and body.get("ok"):
        ok("agent source inject returns ok=true")
    else:
        fail("agent source inject returns ok=true", f"HTTP {status} body={body}")


def test_newlines_in_message_dont_crash():
    status, _ = post(f"/agents/{PROBE_NAME}/inject", {"message": "line1\nline2\r\nline3"})
    if status in (200, 422):
        ok("newlines in message don't cause 500")
    else:
        fail("newlines in message don't cause 500", f"HTTP {status}")


def test_empty_message_accepted():
    status, _ = post(f"/agents/{PROBE_NAME}/inject", {"message": ""})
    if status == 200:
        ok("empty message accepted without error")
    else:
        fail("empty message accepted without error", f"HTTP {status}")


def test_raw_source_lands_in_real_terminal(tmp_dir: Path):
    """The strongest e2e check: verify the message actually arrived in the
    disposable terminal's real capture log, delivered via real AppleScript/
    iTerm2 — not just that the backend claims success."""
    marker = "__raw_prefix_test__"
    capture_log = tmp_dir / "capture.log"
    before_size = capture_log.stat().st_size if capture_log.exists() else 0

    status, body = post(f"/agents/{PROBE_NAME}/inject", {"message": marker, "source": "raw"})
    if not (status == 200 and body.get("ok") and body.get("injected")):
        fail("raw source actually delivered to terminal", f"HTTP {status} body={body}")
        return

    time.sleep(0.5)
    if not capture_log.exists():
        fail("raw source actually delivered to terminal", "capture.log not found")
        return
    with open(capture_log) as f:
        f.seek(before_size)
        new_text = f.read()
    if marker in new_text:
        ok("raw source: message actually landed in the real terminal (verified via capture.log)")
    else:
        fail("raw source actually delivered to terminal", f"capture.log new bytes: {new_text!r}")


def test_audit_log_confirms_no_prefix(tmp_dir: Path):
    marker = "__audit_log_prefix_test__"
    log_path = tmp_dir / "session" / "inject.log"
    before_size = log_path.stat().st_size if log_path.exists() else 0

    status, body = post(f"/agents/{PROBE_NAME}/inject", {"message": marker, "source": "raw"})
    if not (status == 200 and body.get("ok")):
        fail("audit log confirms no prefix", f"HTTP {status} body={body}")
        return

    if not log_path.exists():
        fail("audit log confirms no prefix", "log file not found")
        return
    with open(log_path) as f:
        f.seek(before_size)
        new_lines = f.read()
    if f"msg='{marker}'" in new_lines and "source=raw" in new_lines:
        ok("inject.log confirms message injected without prefix")
    else:
        fail("inject.log confirms message injected without prefix", f"new log lines: {new_lines!r}")


def test_inject_sends_return_via_iterm():
    """Verify _inject_via_iterm sends Enter within the iTerm2 tell block (not via System Events)."""
    main_py = Path(__file__).parent.parent / "backend" / "main.py"
    text = main_py.read_text()
    assert "ASCII character 13" in text, \
        "_inject_via_iterm does not use ASCII character 13 — Enter won't be pressed after injection"
    assert not ("System Events" in text and "key code 36" in text), \
        "_inject_via_iterm still uses System Events key code 36"


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Inject Endpoint Tests ===\n")
    get("/health")

    test_unknown_agent_returns_404()
    test_inject_sends_return_via_iterm()

    print("\n→ Setting up disposable probe terminal (throwaway agent, closed at the end)...")
    ctx = setup_probe()
    print(f"  probe agent={PROBE_NAME!r} tty={ctx['tty']} tmp_dir={ctx['tmp_dir']}\n")
    try:
        test_inject_response_shape()
        test_voice_source_returns_ok()
        test_agent_source_returns_ok()
        test_newlines_in_message_dont_crash()
        test_empty_message_accepted()
        test_raw_source_lands_in_real_terminal(ctx["tmp_dir"])
        test_audit_log_confirms_no_prefix(ctx["tmp_dir"])
    finally:
        print("\n→ Tearing down probe terminal...")
        teardown_probe(ctx)

    print(f"\n══════════════════════════════════")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"══════════════════════════════════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
