"""Speech clips for the phone (backend/speech_store.py + /device/agents/{name}/speech)."""
import base64
import sys
import threading as _threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
import speech_store as ss  # noqa: E402


def test_parts_fit_the_envelope_and_reassemble(tmp_path):
    store = ss.SpeechStore(tmp_path)
    audio = bytes(range(256)) * 400  # 102400 bytes → 3 parts
    meta = store.put("Alpha", "abc", audio, ts=1, text="hola", duration_ms=1500)
    assert meta["parts"] == 3
    chunks = [store.part("Alpha", "abc", i) for i in range(3)]
    assert all(len(c["b64"]) < 65535 for c in chunks)
    assert b"".join(base64.b64decode(c["b64"]) for c in chunks) == audio
    assert store.part("Alpha", "abc", 3) is None
    assert store.part("Alpha", "../etc", 0) is None


def test_keeps_the_last_20_for_an_hour(tmp_path):
    now = [10_000.0]
    store = ss.SpeechStore(tmp_path, now=lambda: now[0])
    for i in range(25):
        store.put("Alpha", f"c{i}", b"x", ts=int(now[0] * 1000) + i, text=str(i), duration_ms=None)
    items = store.list("Alpha")
    assert [i["id"] for i in items] == [f"c{i}" for i in range(5, 25)]
    assert [i["id"] for i in store.list("Alpha", after=int(now[0] * 1000) + 23)] == ["c24"]
    now[0] += ss.MAX_AGE_S + 1
    assert store.list("Alpha") == []


class _NoStartThread(_threading.Thread):
    def start(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).parent.parent))
    if "backend.main" in sys.modules:
        del sys.modules["backend.main"]
    monkeypatch.setattr(_threading, "Thread", _NoStartThread)
    import backend.main as main
    monkeypatch.undo()
    monkeypatch.setattr(main, "REGISTRY_FILE", tmp_path / "registry.json")
    (tmp_path / "registry.json").write_text('{"Alpha": {"path": "/x"}, "Beta": {"path": "/y"}}')
    monkeypatch.setattr(main, "_speech", ss.SpeechStore(tmp_path / "speech"))
    return TestClient(main.app)


def test_widget_puts_phone_reads(client):
    res = client.put("/agents/Alpha/speech/s1", content=b"m4a-bytes", headers={"X-Speech-Ts": "1794000000000", "X-Speech-Text": "hola%20Jos%C3%A9", "X-Speech-Duration-Ms": "1200"})
    assert res.json() == {"ok": True, "parts": 1}
    [item] = client.get("/device/agents/Alpha/speech", params={"after": 0}).json()["items"]
    assert item == {"id": "s1", "ts": 1794000000000, "text": "hola José", "durationMs": 1200, "mime": "audio/mp4", "parts": 1, "route": "mac"}
    part = client.get("/device/agents/Alpha/speech/s1", params={"part": 0}).json()
    assert base64.b64decode(part["b64"]) == b"m4a-bytes"
    assert client.put("/device/agents/Alpha/speech/s2", content=b"x").status_code == 405, "the phone only reads"
    assert client.get("/device/agents/Nobody/speech").status_code == 404


def test_one_list_for_the_whole_mac(client):
    client.put("/agents/Beta/speech/b1", content=b"b", headers={"X-Speech-Ts": "20"})
    client.put("/agents/Alpha/speech/a1", content=b"a", headers={"X-Speech-Ts": "10"})
    client.put("/agents/Alpha/speech/a2", content=b"a", headers={"X-Speech-Ts": "30"})
    items = client.get("/device/speech").json()["items"]
    assert [(i["agent"], i["id"]) for i in items] == [("Alpha", "a1"), ("Beta", "b1"), ("Alpha", "a2")]
    assert [i["id"] for i in client.get("/device/speech", params={"after": 20}).json()["items"]] == ["a2"]


def test_answer_through_the_medium_you_were_spoken_to(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).parent.parent))
    if "backend.main" in sys.modules:
        del sys.modules["backend.main"]
    monkeypatch.setattr(_threading, "Thread", _NoStartThread)
    import backend.main as main
    monkeypatch.undo()
    monkeypatch.setattr(main, "REPLY_ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr(main, "_chat", __import__("chat_history").ChatHistory(tmp_path / "chat"))
    feed = lambda env: main._on_chat_message("las/agent/Alpha/inbox", __import__("json").dumps(env).encode())
    assert main._reply_route("Alpha") == "mac", "default: this Mac"
    feed({"from": "Alpha", "to": "Alpha", "source": "human", "text": "desde el teléfono", "via": "device:jose-iphone", "ts": 1})
    assert main._reply_route("Alpha") == "jose-iphone"
    feed({"from": "Relay", "to": "Alpha", "source": "agent", "text": "un agente no cambia nada", "ts": 2})
    assert main._reply_route("Alpha") == "jose-iphone"
    feed({"from": "Alpha", "to": "Alpha", "source": "human", "text": "por el mic del widget", "ts": 3})
    assert main._reply_route("Alpha") == "mac"
    feed({"from": "jose-iphone", "to": "Alpha", "source": "human", "via": "device", "text": "escrito en el teléfono", "ts": 4})
    assert main._reply_route("Alpha") == "jose-iphone"
