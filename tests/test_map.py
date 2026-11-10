"""The map (docs/adr/0007): elements an agent adds by hand — repos and URLs.

Declared as `map` in the agent's .las-agent.json, read/written by the backend
(GET/POST/DELETE /agents/{name}/map), driven by `las map`."""
import json
import subprocess
import sys
import threading as _threading
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from cli.agent_config import map_element_id, map_elements_of, with_map_element


# ── the schema helpers ──────────────────────────────────────────────────────

def test_map_elements_of_is_tolerant_unique_and_ordered():
    assert map_elements_of(None) == []
    assert map_elements_of({"map": "x"}) == []
    config = {"map": [
        {"type": "repo", "path": " a "}, {"type": "url", "url": "https://x.y", "label": " X "},
        {"type": "repo", "path": "a"}, {"type": "nope", "path": "b"}, {"type": "url"}, "junk", None,
    ]}
    assert map_elements_of(config) == [{"type": "repo", "path": "a"}, {"type": "url", "url": "https://x.y", "label": "X"}]


def test_with_map_element_adds_once_replaces_in_place_and_removes():
    config = {"map": [{"type": "repo", "path": "a"}, {"type": "url", "url": "https://x.y"}]}
    assert map_element_id({"type": "repo", "path": "a"}) == "repo:a"
    assert with_map_element(config, {"type": "repo", "path": "b"})[-1] == {"type": "repo", "path": "b"}
    relabeled = with_map_element(config, {"type": "repo", "path": "a", "label": "A"})
    assert relabeled[0] == {"type": "repo", "path": "a", "label": "A"} and len(relabeled) == 2
    assert with_map_element(config, {"type": "repo", "path": "a"}, added=False) == [{"type": "url", "url": "https://x.y"}]


# ── backend ────────────────────────────────────────────────────────────────

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
    folder = tmp_path / "Monkey"
    folder.mkdir()
    (folder / ".las-agent.json").write_text(json.dumps({"name": "Monkey", "locale": "es-MX"}))
    client.post("/agents", json={"name": "Monkey", "voice": "Paulina", "path": str(folder)})
    return main, client, folder


def _git_repo(path: Path, remote: str | None = None) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    if remote:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    return path


def _file(folder):
    return json.loads((folder / ".las-agent.json").read_text())


def test_add_repo_inside_the_agent_folder_is_stored_relative_and_read_live(app):
    _main, client, folder = app
    _git_repo(folder / "relay-ros", "git@github.com:acme/relay-ros.git")
    view = client.post("/agents/Monkey/map", json={"type": "repo", "path": str(folder / "relay-ros")}).json()
    assert _file(folder)["map"] == [{"type": "repo", "path": "relay-ros"}]
    assert _file(folder)["locale"] == "es-MX", "the rest of the file is kept"
    [row] = view["elements"]
    assert row["id"] == "repo:relay-ros" and row["label"] == "relay-ros"
    assert row["exists"] is True and row["github"] == "acme/relay-ros" and row["branch"] == "main"


def test_add_repo_outside_is_absolute_and_a_non_git_folder_is_refused(app, tmp_path):
    _main, client, folder = app
    other = _git_repo(tmp_path / "elsewhere", "https://github.com/acme/other")
    client.post("/agents/Monkey/map", json={"type": "repo", "path": str(other), "label": "Other"})
    assert _file(folder)["map"] == [{"type": "repo", "path": str(other.resolve()), "label": "Other"}]
    (tmp_path / "plain").mkdir()
    assert client.post("/agents/Monkey/map", json={"type": "repo", "path": str(tmp_path / "plain")}).status_code == 422


def test_urls_add_idempotently_bad_ones_are_refused_and_remove_by_id(app):
    _main, client, folder = app
    client.post("/agents/Monkey/map", json={"type": "url", "url": "https://github.com/acme/x/pulls"})
    view = client.post("/agents/Monkey/map", json={"type": "url", "url": "https://github.com/acme/x/pulls", "label": "PRs"}).json()
    assert [(e["id"], e["label"]) for e in view["elements"]] == [("url:https://github.com/acme/x/pulls", "PRs")]
    assert client.post("/agents/Monkey/map", json={"type": "url", "url": "ftp://x"}).status_code == 422
    assert client.post("/agents/Monkey/map", json={"type": "boat"}).status_code == 422
    view = client.delete("/agents/Monkey/map", params={"id": "url:https://github.com/acme/x/pulls"}).json()
    assert view["elements"] == [] and _file(folder)["map"] == []
    assert client.delete("/agents/Monkey/map", params={"id": "nonsense"}).status_code == 422


def test_a_repo_that_disappeared_stays_listed_as_missing(app):
    _main, client, folder = app
    (folder / ".las-agent.json").write_text(json.dumps({"name": "Monkey", "map": [{"type": "repo", "path": "gone"}]}))
    [row] = client.get("/agents/Monkey/map").json()["elements"]
    assert row["exists"] is False and row["github"] is None


# ── CLI ────────────────────────────────────────────────────────────────────

def test_cli_add_list_remove_call_the_backend(monkeypatch, tmp_path):
    from cli.commands import map as map_cmd
    calls = []
    view = {"agent": "Monkey", "elements": [{"id": "url:https://x.y", "type": "url", "url": "https://x.y", "label": "x.y"}]}
    monkeypatch.setattr(map_cmd, "resolve_agent_name", lambda n: n or "Monkey")
    monkeypatch.setattr(map_cmd.api, "get", lambda p: calls.append(("get", p)) or view)
    monkeypatch.setattr(map_cmd.api, "post", lambda p, d=None: calls.append(("post", p, d)) or view)
    monkeypatch.setattr(map_cmd.api, "delete", lambda p: calls.append(("delete", p)) or {"agent": "Monkey", "elements": []})
    opened = []
    monkeypatch.setattr(map_cmd.subprocess, "run", lambda args, **k: opened.append(args))
    runner = CliRunner()
    out = runner.invoke(map_cmd.map_group, [])
    assert out.exit_code == 0 and opened[-1] == ["open", "localagentsociety://Monkey?action=map"], "bare `las map` opens the window"
    runner.invoke(map_cmd.map_group, ["open", "Minis App"])
    assert opened[-1] == ["open", "localagentsociety://Minis%20App?action=map"]
    out = runner.invoke(map_cmd.map_group, ["list"])
    assert out.exit_code == 0 and "x.y" in out.output and "id: url:https://x.y" in out.output
    runner.invoke(map_cmd.map_group, ["--agent", "Teli", "add", "url", "https://x.y", "--label", "X"])
    assert calls[-1] == ("post", "/agents/Teli/map", {"type": "url", "url": "https://x.y", "label": "X"})
    runner.invoke(map_cmd.map_group, ["add", "repo", str(tmp_path)])
    assert calls[-1] == ("post", "/agents/Monkey/map", {"type": "repo", "path": str(tmp_path.resolve()), "label": None})
    out = runner.invoke(map_cmd.map_group, ["remove", "url:https://x.y"])
    assert calls[-1] == ("delete", "/agents/Monkey/map?id=url%3Ahttps%3A%2F%2Fx.y") and "nothing on the map" in out.output


# ── security mode ──────────────────────────────────────────────────────────

def test_security_mode_defaults_to_dangerous_and_only_takes_the_two_modes(app):
    from cli.agent_config import security_mode_of
    assert security_mode_of(None) == "dangerous" and security_mode_of({"security_mode": "weird"}) == "dangerous"
    _main, client, folder = app
    assert client.get("/agents/Monkey/config").json()["security_mode"] == "dangerous"
    assert client.patch("/agents/Monkey/config", json={"security_mode": "safe"}).json()["security_mode"] == "safe"
    assert _file(folder)["security_mode"] == "safe"
    assert client.patch("/agents/Monkey/config", json={"security_mode": "yolo"}).status_code == 422


def test_cli_security_shows_and_sets(monkeypatch):
    from cli.commands import agents as agents_cmd
    calls = []
    monkeypatch.setattr(agents_cmd, "resolve_agent_name", lambda n: n or "Monkey")
    monkeypatch.setattr(agents_cmd.api, "get", lambda p: calls.append(("get", p)) or {"security_mode": "dangerous"})
    monkeypatch.setattr(agents_cmd.api, "patch", lambda p, d=None: calls.append(("patch", p, d)) or {"security_mode": d["security_mode"]})
    out = CliRunner().invoke(agents_cmd.security, [])
    assert "Monkey: dangerous" in out.output
    out = CliRunner().invoke(agents_cmd.security, ["safe"])
    assert calls[-1] == ("patch", "/agents/Monkey/config", {"security_mode": "safe"}) and "Monkey: safe" in out.output
