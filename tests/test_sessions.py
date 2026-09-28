"""Connected sessions (docs/adr/0004 phase 2): an agent may have a Claude, a
Codex and a shell attached at once. The backend keeps the list, elects the
default (last used), publishes it retained for the bridges, prunes dead
processes, and routes `send` to the default / one session / all of them."""
import os
import sys
import threading as _threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class _NoStartThread(_threading.Thread):
    def start(self):
        pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).parent.parent))
    if "backend.main" in sys.modules:
        del sys.modules["backend.main"]
    monkeypatch.setattr(_threading, "Thread", _NoStartThread)
    import backend.main as main
    monkeypatch.undo()
    monkeypatch.setattr(main, "REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(main, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(main, "PORTS_FILE", tmp_path / "ports.json")
    published = []
    monkeypatch.setattr(main, "_vortexia_publish", lambda topic, envelope, retain=False: (published.append((topic, envelope, retain)), True)[1])
    monkeypatch.setattr(main, "_pid_alive", lambda pid: int(pid) != 999)
    main.published = published
    client = TestClient(main.app)
    client.post("/agents", json={"name": "Robo", "voice": "Samantha", "path": str(tmp_path)})
    return main, client


def _register(client, sid, runtime, pid=1):
    r = client.post("/agents/Robo/sessions", json={"sid": sid, "runtime": runtime, "pid": pid, "cwd": "/x"})
    assert r.status_code == 200, r.text
    return r.json()


def _default_publishes(main):
    return [(t, e) for t, e, retain in main.published if t == "las/agent/Robo/default-session" and retain]


def test_register_makes_the_new_session_the_default_and_publishes_it_retained(app):
    main, client = app
    view = _register(client, "claude-1", "claude")
    assert view["default"] == "claude-1"
    assert _default_publishes(main)[-1][1]["sid"] == "claude-1"
    view = _register(client, "shell-1", "shell")
    assert view["default"] == "shell-1", "the session you just opened is the one you're using"
    assert [s["sid"] for s in view["sessions"]] == ["shell-1", "claude-1"]
    assert _default_publishes(main)[-1][1] ["runtime"] == "shell"


def test_touch_moves_the_default_and_delete_hands_it_to_the_next_most_recent(app):
    main, client = app
    _register(client, "claude-1", "claude")
    _register(client, "shell-1", "shell")
    assert client.post("/agents/Robo/sessions/claude-1/touch").json()["default"] == "claude-1"
    assert _default_publishes(main)[-1][1]["sid"] == "claude-1"
    assert client.post("/agents/Robo/sessions/nope/touch").status_code == 404
    gone = client.delete("/agents/Robo/sessions/claude-1").json()
    assert gone["removed"] is True and gone["default"] == "shell-1"
    empty = client.delete("/agents/Robo/sessions/shell-1").json()
    assert empty["default"] is None and empty["sessions"] == []
    assert _default_publishes(main)[-1][1] == {"sid": None, "runtime": None, "ts": _default_publishes(main)[-1][1]["ts"]}, "no default -> nobody holds the agent mailbox, it queues"


def test_dead_processes_are_pruned_on_read(app):
    main, client = app
    _register(client, "claude-1", "claude", pid=1)
    _register(client, "zombie", "shell", pid=999)
    view = client.get("/agents/Robo/sessions").json()
    assert [s["sid"] for s in view["sessions"]] == ["claude-1"]
    assert view["default"] == "claude-1"


def test_send_routes_to_default_one_session_by_id_or_runtime_or_all(app):
    main, client = app
    _register(client, "claude-1", "claude")
    _register(client, "codex-1", "codex")
    _register(client, "shell-1", "shell")

    r = client.post("/agents/send", json={"message": "hi", "to": "Robo", "from_agent": "Vortexia"}).json()
    assert r["mode"] == "direct"
    assert main.published[-1][0] == "las/agent/Robo/inbox", "plain send = the agent inbox, held by the default session"

    r = client.post("/agents/send", json={"message": "ls", "to": "Robo", "session": "shell-1", "from_agent": "Vortexia"}).json()
    assert r["mode"] == "session"
    assert main.published[-1][0] == "las/agent/Robo/sessions/shell-1/inbox"
    assert main.published[-1][1]["session"] == "shell-1"

    r = client.post("/agents/send", json={"message": "fix", "to": "Robo", "session": "claude"}).json()
    assert r["mode"] == "session"
    assert main.published[-1][0] == "las/agent/Robo/sessions/claude-1/inbox", "a runtime name picks its most recent session"

    before = len(main.published)
    r = client.post("/agents/send", json={"message": "all hands", "to": "Robo", "all_sessions": True}).json()
    assert r["mode"] == "all-sessions" and r["injected"] is True
    topics = sorted(t for t, e, _ in main.published[before:])
    assert topics == sorted(f"las/agent/Robo/sessions/{sid}/inbox" for sid in ("claude-1", "codex-1", "shell-1"))

    assert client.post("/agents/send", json={"message": "x", "to": "Robo", "session": "nope"}).status_code == 404
    client.delete("/agents/Robo/sessions/claude-1"); client.delete("/agents/Robo/sessions/codex-1"); client.delete("/agents/Robo/sessions/shell-1")
    assert client.post("/agents/send", json={"message": "x", "to": "Robo", "all_sessions": True}).status_code == 404, "never publish into a session mailbox nobody will hold"
