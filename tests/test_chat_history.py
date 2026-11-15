"""Per-agent chat history (backend/chat_history.py, GET /agents/{name}/chat
and its /device/ alias): the widget's three bubble kinds, kept for the phone
app's agent card."""
import sys
import threading as _threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
import chat_history as ch  # noqa: E402


def env(i, frm, to, text, **extra):
    return {"id": f"m{i}", "ts": 1000 + i, "from": frm, "to": to, "text": text, **extra}


def test_three_bubble_kinds_and_outgoing_land_in_the_right_histories(tmp_path):
    h = ch.ChatHistory(tmp_path)
    h.record(env(1, "Alpha", "Alpha", "dictado", source="human"))
    h.record(env(2, "queue", "Alpha", "lo que dijo", kind="speak", source="system"))
    h.record(env(3, "Relay", "Alpha", "hola Alpha"))
    h.record(env(4, "Alpha", "Relay", "hola Relay"))
    assert [m["text"] for m in h.query("Alpha")] == ["dictado", "lo que dijo", "hola Alpha", "hola Relay"]
    assert [m["text"] for m in h.query("Relay")] == ["hola Alpha", "hola Relay"]
    assert h.query("queue") == []


def test_housekeeping_and_duplicates_are_skipped(tmp_path):
    h = ch.ChatHistory(tmp_path)
    h.record(env(1, "Alpha", "Alpha", "[las-channel-probe] probe_id=1", kind="probe"))
    h.record(env(2, "Alpha", "Alpha", '[las-mic-selftest] reply with just "OK"'))
    h.record(env(3, "Relay", "Alpha", "copia", kind="cc"))
    h.record(env(4, "Relay", "Alpha", "una vez"))
    h.record(env(4, "Relay", "Alpha", "una vez"), session="claude-1")  # also seen on the session inbox
    assert [m["text"] for m in h.query("Alpha")] == ["una vez"]
    no_id = {"ts": 2000, "from": "Relay", "to": "Alpha", "text": "sin id"}
    h.record(dict(no_id))
    h.record(dict(no_id), session="claude-1")
    assert [m["text"] for m in h.query("Alpha")] == ["una vez", "sin id"]
    assert h.query("Alpha")[-1]["id"]


def test_after_limit_cap_and_restart(tmp_path):
    h = ch.ChatHistory(tmp_path, max_per_agent=5)
    for i in range(12):
        h.record(env(i, "Relay", "Alpha", f"t{i}"))
    assert [m["text"] for m in h.query("Alpha")] == [f"t{i}" for i in range(7, 12)], "the last 5"
    assert [m["text"] for m in h.query("Alpha", after=1010)] == ["t11"]
    assert [m["text"] for m in h.query("Alpha", limit=2)] == ["t10", "t11"]
    again = ch.ChatHistory(tmp_path, max_per_agent=5)
    assert [m["text"] for m in again.query("Alpha")] == [f"t{i}" for i in range(7, 12)], "survives a restart"
    again.record(env(11, "Relay", "Alpha", "t11"))
    assert len(again.query("Alpha")) == 5, "dedup survives a restart too"


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
    (tmp_path / "registry.json").write_text('{"Alpha": {"path": "/x"}}')
    monkeypatch.setattr(main, "_chat", ch.ChatHistory(tmp_path / "chat"))
    return main, TestClient(main.app)


def test_endpoint_and_device_alias(app):
    main, client = app
    main._on_chat_message("las/agent/Alpha/sessions/claude-1/inbox", b'{"id":"a","ts":5,"from":"Relay","to":"Alpha","text":"hola"}')
    main._on_chat_message("las/speak", b'{"id":"b","ts":6,"from":"queue","to":"Alpha","text":"dije","kind":"speak"}')
    main._on_chat_message("las/agent/Alpha/inbox", b"not json")
    res = client.get("/device/agents/Alpha/chat", params={"after": 0})
    assert res.status_code == 200
    msgs = res.json()["messages"]
    assert [(m["text"], m.get("session")) for m in msgs] == [("hola", "claude-1"), ("dije", None)]
    assert client.get("/agents/Alpha/chat", params={"after": 5}).json()["messages"][0]["id"] == "b"
    assert client.get("/agents/Nobody/chat").status_code == 404
