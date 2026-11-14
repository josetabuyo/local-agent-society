"""GET /society/tree (and its /device/ alias for vortexia's gateway): the whole
society nested by folder, each node with its scope, sessions and map — the
data behind the phone app's panel (vortexia docs/adr/0001 §8)."""
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
    monkeypatch.setenv("VORTEXIA_ENV_NAME", "ba-mac")
    client = TestClient(main.app)

    def agent(name, folder, **config):
        folder.mkdir(parents=True)
        (folder / ".git").mkdir()
        (folder / ".las-agent.json").write_text(json.dumps({"name": name, "locale": "es-MX", **config}))
        assert client.post("/agents", json={"name": name, "voice": "Paulina", "path": str(folder)}).status_code == 200

    agent("Relay", tmp_path / "relay", color="#112233", short_description="Robots",
          map=[{"type": "url", "url": "https://x.y/pulls", "label": "PRs"}, {"type": "repo", "path": "/a/b/ros"}])
    agent("RelayRos", tmp_path / "relay" / "ros")
    agent("Alpha", tmp_path / "alpha", friends=["Relay"])
    return main, client


def test_tree_nests_subordinates_and_carries_each_agents_tile(app):
    _main, client = app
    res = client.get("/society/tree")
    assert res.status_code == 200
    tree = res.json()
    assert tree["env"] == "ba-mac"
    assert [a["name"] for a in tree["agents"]] == ["Alpha", "Relay"], "roots only, sorted"
    relay = tree["agents"][1]
    assert [c["name"] for c in relay["children"]] == ["RelayRos"], "a subordinate lives under its parent"
    assert relay["children"][0]["children"] == []
    assert relay["color"] == "#112233" and relay["short_description"] == "Robots" and relay["locale"] == "es-MX"
    assert relay["map"] == [{"type": "url", "url": "https://x.y/pulls", "label": "PRs"}, {"type": "repo", "label": "ros"}]
    assert tree["agents"][0]["friends"] == ["Relay"]
    assert relay["sessions"] == [] and relay["inactive"] is False


def test_tree_lists_sessions_with_titles(app):
    _main, client = app
    client.post("/agents/Alpha/sessions", json={"sid": "claude-1-aa", "runtime": "claude", "pid": 1})
    client.put("/agents/Alpha/sessions/claude-1-aa/title", json={"title": "Phone app"})
    alpha = client.get("/society/tree").json()["agents"][0]
    [s] = alpha["sessions"]
    assert s["sid"] == "claude-1-aa" and s["runtime"] == "claude" and s["title"] == "Phone app" and s["default"] is True


def test_etag_gives_304_and_device_alias_serves_the_same(app):
    _main, client = app
    first = client.get("/society/tree")
    etag = first.headers["etag"]
    assert client.get("/society/tree", headers={"If-None-Match": etag}).status_code == 304
    device = client.get("/device/society/tree")
    assert device.status_code == 200 and device.headers["etag"] == etag and device.json() == first.json()
    client.post("/agents/Alpha/sessions", json={"sid": "shell-2-bb", "runtime": "shell", "pid": 2})
    assert client.get("/society/tree", headers={"If-None-Match": etag}).status_code == 200, "a change changes the ETag"
