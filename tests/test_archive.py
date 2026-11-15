"""The archive (cli/agent_config.py ARCHIVE_KEY, /agents/{name}/archive): map
elements and friends put away — off the map, still at hand; restorable; the
archive's ✕ forgets them, and a friend is then only unlinked."""
import json
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
    for attr, file in (("REGISTRY_FILE", "registry.json"), ("SESSIONS_FILE", "sessions.json"), ("INACTIVE_FILE", "inactive.json"), ("PORTS_FILE", "ports.json")):
        monkeypatch.setattr(main, attr, tmp_path / file)
    monkeypatch.setattr(main, "_vortexia_publish", lambda *a, **k: True)
    monkeypatch.setattr(main, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(main, "_watch_relay_directory", lambda: None)
    client = TestClient(main.app)
    for name, folder in (("Alpha", tmp_path / "alpha"), ("Old", tmp_path / "old")):
        folder.mkdir()
        (folder / ".git").mkdir()
        (folder / ".las-agent.json").write_text(json.dumps({"name": name, "locale": "es-MX"}))
        assert client.post("/agents", json={"name": name, "voice": "Paulina", "path": str(folder)}).status_code == 200
    (tmp_path / "alpha" / "tool" / ".git").mkdir(parents=True)
    assert client.put("/agents/Alpha/friends/Old").status_code == 200
    assert client.post("/agents/Alpha/map", json={"type": "repo", "path": str(tmp_path / "alpha" / "tool")}).status_code == 200
    return main, client, tmp_path


def cfg(tmp_path):
    return json.loads((tmp_path / "alpha" / ".las-agent.json").read_text())


def test_archive_moves_off_the_map_and_restore_puts_it_back(app):
    _main, client, tmp = app
    res = client.post("/agents/Alpha/archive", json={"id": "friend:Old"})
    assert res.status_code == 200
    assert [r["id"] for r in res.json()["archive"]] == ["friend:Old"]
    assert "Old" not in cfg(tmp).get("friends", [])
    client.post("/agents/Alpha/archive", json={"id": "repo:tool"})
    assert cfg(tmp)["map"] == []
    tree = client.get("/device/society/tree").json()
    alpha = next(a for a in tree["agents"] if a["name"] == "Alpha")
    assert [(a["id"], a["label"]) for a in alpha["archive"]] == [("friend:Old", "Old"), ("repo:tool", "tool")]
    assert alpha["map"] == [] and alpha["friends"] == []
    client.post("/agents/Alpha/archive/restore", json={"id": "repo:tool"})
    assert [e["path"] for e in cfg(tmp)["map"]] == ["tool"]
    assert [r["id"] for r in client.get("/device/agents/Alpha/archive").json()["archive"]] == ["friend:Old"]


def test_forget_drops_it_for_good_but_never_the_agent(app):
    _main, client, tmp = app
    client.post("/agents/Alpha/archive", json={"id": "friend:Old"})
    assert client.delete("/agents/Alpha/archive", params={"id": "friend:Old"}).json()["archive"] == []
    assert "Old" not in cfg(tmp).get("friends", [])
    assert "Old" in client.get("/agents").json(), "the agent itself stays registered"
    assert (tmp / "old" / ".las-agent.json").exists()


def test_errors_say_where_it_is_not(app):
    _main, client, _tmp = app
    assert client.post("/agents/Alpha/archive", json={"id": "friend:Nobody"}).status_code == 404
    assert client.post("/agents/Alpha/archive/restore", json={"id": "friend:Old"}).status_code == 404
    assert client.delete("/agents/Alpha/archive", params={"id": "repo:tool"}).status_code == 404
