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


def test_a_whole_agent_is_archived_off_the_tree_and_comes_back(app, monkeypatch):
    main, client, tmp = app
    monkeypatch.setattr(main, "ARCHIVED_AGENTS_FILE", tmp / "archived-agents.json")
    (tmp / "alpha" / "kid" / ".git").mkdir(parents=True)
    (tmp / "alpha" / "kid" / ".las-agent.json").write_text(json.dumps({"name": "Kid", "locale": "es-MX"}))
    assert client.post("/agents", json={"name": "Kid", "voice": "Paulina", "path": str(tmp / "alpha" / "kid")}).status_code == 200
    assert client.post("/agents/Alpha/archived").json()["archived"] is True
    tree = client.get("/device/society/tree").json()
    assert [a["name"] for a in tree["agents"]] == ["Kid", "Old"], "Alpha leaves; its subordinate moves up"
    assert [(a["name"], a["path"]) for a in tree["archived"]] == [("Alpha", str(tmp / "alpha"))]
    assert "Alpha" in json.loads((tmp / "inactive.json").read_text()), "its widget is put away too"
    assert (tmp / "alpha" / ".las-agent.json").exists() and "Alpha" in client.get("/agents").json(), "nothing deleted"
    assert client.delete("/agents/Alpha/archived").status_code == 200
    tree = client.get("/device/society/tree").json()
    assert tree["archived"] == [] and [c["name"] for c in next(a for a in tree["agents"] if a["name"] == "Alpha")["children"]] == ["Kid"]
    assert client.delete("/agents/Alpha/archived").status_code == 404


def test_main_screen_flag_is_declared_and_carried_by_the_tree(app):
    _main, client, tmp = app
    assert client.patch("/agents/Old/config", json={"main_screen": "no"}).status_code == 422
    res = client.patch("/agents/Old/config", json={"main_screen": False})
    assert res.status_code == 200 and res.json()["main_screen"] is False, "the view says it (the widget's checkbox reads it)"
    assert client.get("/agents/Alpha/config").json()["main_screen"] is True
    tree = {a["name"]: a for a in client.get("/device/society/tree").json()["agents"]}
    assert tree["Old"]["main_screen"] is False, "still in the tree: it shows inside its context"
    assert tree["Alpha"]["main_screen"] is True, "default: shown"
    assert json.loads((tmp / "old" / ".las-agent.json").read_text())["main_screen"] is False


def test_tts_speed_is_validated_and_kept(app):
    _main, client, tmp = app
    for bad in ("slow", 0.2, 3, True):
        assert client.patch("/agents/Old/config", json={"tts_speed": bad}).status_code == 422
    res = client.patch("/agents/Old/config", json={"tts_speed": 0.8})
    assert res.status_code == 200 and res.json()["config"]["tts_speed"] == 0.8
    assert json.loads((tmp / "old" / ".las-agent.json").read_text())["tts_speed"] == 0.8
