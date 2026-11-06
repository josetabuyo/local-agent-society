"""las-friends: the agents one agent is linked to (`friends` in its .las-agent.json).

Directed like a follow, mutual when both sides list each other. The backend
reads/writes them (GET/PUT/DELETE /agents/{name}/friends[/{friend}]), the
CLI shows/edits them (`las agent friends`) and fans a message out to all of
them (`las agent send --to X --friends`)."""
import json
import sys
import threading as _threading
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from cli.agent_config import friends_of, with_friend


# ── the schema helpers ──────────────────────────────────────────────────────

def test_friends_of_is_tolerant_unique_ordered_and_never_self():
    assert friends_of(None) == []
    assert friends_of({"friends": "Vortexia"}) == [], "not a list -> ignored, never crashes"
    config = {"name": "Me", "friends": ["Vortexia", " Teli ", "Vortexia", "", 3, "Me", None]}
    assert friends_of(config) == ["Vortexia", "Teli"]


def test_with_friend_appends_once_and_removes():
    config = {"name": "Me", "friends": ["A"]}
    assert with_friend(config, "B") == ["A", "B"]
    assert with_friend(config, "A") == ["A"], "idempotent"
    assert with_friend(config, "A", linked=False) == []
    assert with_friend(config, "Z", linked=False) == ["A"]


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
    monkeypatch.setitem(main._relay_directory_cache, "entries", [])
    client = TestClient(main.app)
    for name in ("Monkey", "Vortexia", "Teli"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ".las-agent.json").write_text(json.dumps({"name": name, "voice": "Paulina"}))
        client.post("/agents", json={"name": name, "voice": "Paulina", "path": str(folder)})
    return main, client, tmp_path


def _file(tmp_path, name):
    return json.loads((tmp_path / name / ".las-agent.json").read_text())


def test_link_writes_the_agents_own_file_in_order_and_unlink_removes_only_one_side(app):
    _main, client, tmp_path = app
    assert client.get("/agents/Monkey/friends").json() == {"agent": "Monkey", "friends": []}
    client.put("/agents/Monkey/friends/Vortexia")
    view = client.put("/agents/Monkey/friends/Teli").json()
    assert [f["name"] for f in view["friends"]] == ["Vortexia", "Teli"]
    assert _file(tmp_path, "Monkey")["friends"] == ["Vortexia", "Teli"]
    assert _file(tmp_path, "Monkey")["voice"] == "Paulina", "the rest of the file is kept"
    assert client.put("/agents/Monkey/friends/Teli").json()["friends"][-1]["name"] == "Teli", "idempotent"
    assert _file(tmp_path, "Monkey")["friends"] == ["Vortexia", "Teli"]
    view = client.delete("/agents/Monkey/friends/Vortexia").json()
    assert [f["name"] for f in view["friends"]] == ["Teli"]


def test_mutual_only_when_both_sides_link(app):
    _main, client, _tmp = app
    client.put("/agents/Monkey/friends/Vortexia")
    assert client.get("/agents/Monkey/friends").json()["friends"][0]["mutual"] is False, "a follow, not a handshake"
    client.put("/agents/Vortexia/friends/Monkey")
    assert client.get("/agents/Monkey/friends").json()["friends"][0]["mutual"] is True


def test_friend_rows_carry_widget_and_session_state(app):
    _main, client, _tmp = app
    client.put("/agents/Monkey/friends/Vortexia")
    client.post("/agents/Vortexia/inactive")
    client.post("/agents/Vortexia/sessions", json={"sid": "claude-1", "runtime": "claude", "pid": 1, "cwd": "/x"})
    row = client.get("/agents/Monkey/friends").json()["friends"][0]
    assert row == {"name": "Vortexia", "registered": True, "inactive": True, "sessions": 1, "mutual": False, "color": None}


def test_link_refuses_self_unknown_agents_and_a_broken_file(app):
    _main, client, tmp_path = app
    assert client.put("/agents/Monkey/friends/Monkey").status_code == 422
    assert client.put("/agents/Monkey/friends/Ghost").status_code == 404
    assert client.get("/agents/Ghost/friends").status_code == 404
    (tmp_path / "Monkey" / ".las-agent.json").write_text("{broken,")
    assert client.put("/agents/Monkey/friends/Teli").status_code == 409
    assert (tmp_path / "Monkey" / ".las-agent.json").read_text() == "{broken,", "never overwritten"


def test_a_friend_unregistered_later_is_listed_not_dropped(app):
    _main, client, _tmp = app
    client.put("/agents/Monkey/friends/Teli")
    client.delete("/agents/Teli")
    row = client.get("/agents/Monkey/friends").json()["friends"][0]
    assert row["name"] == "Teli" and row["registered"] is False and row["mutual"] is False
    assert client.delete("/agents/Monkey/friends/Teli").json()["friends"] == [], "and can still be unlinked"


# ── CLI ────────────────────────────────────────────────────────────────────

def test_send_friends_fans_out_to_every_registered_friend(monkeypatch):
    from cli.commands import agents as agents_mod
    sent = []
    monkeypatch.setattr(agents_mod.api, "get", lambda path: {"friends": [{"name": "Vortexia", "registered": True}, {"name": "Gone", "registered": False}, {"name": "Teli", "registered": True}]})
    monkeypatch.setattr(agents_mod.api, "post", lambda path, data=None, timeout=None: (sent.append(data), {"injected": True})[1])
    result = CliRunner().invoke(agents_mod.send, ["en qué andan?", "--to", "Monkey", "--friends", "--from", "Monkey"])
    assert result.exit_code == 0, result.output
    assert [d["to"] for d in sent] == ["Vortexia", "Teli"]
    assert all(d["message"] == "en qué andan?" and d["from_agent"] == "Monkey" for d in sent)
    assert "2/2 friends reached" in result.output


def test_send_friends_needs_a_plain_to(monkeypatch):
    from cli.commands import agents as agents_mod
    assert CliRunner().invoke(agents_mod.send, ["hi", "--scope", "x", "--friends"]).exit_code != 0
    assert CliRunner().invoke(agents_mod.send, ["hi", "--to", "M", "--friends", "--children"]).exit_code != 0
    assert CliRunner().invoke(agents_mod.send, ["hi", "--to", "M", "--friends", "--session", "shell"]).exit_code != 0


def test_friends_command_adds_removes_and_lists(monkeypatch):
    from cli.commands import agents as agents_mod
    calls = []
    view = {"friends": [{"name": "Vortexia", "registered": True, "sessions": 2, "mutual": True, "inactive": False}]}
    monkeypatch.setattr(agents_mod, "resolve_agent_name", lambda n: n or "Monkey")
    monkeypatch.setattr(agents_mod.api, "put", lambda path, data=None: (calls.append(("PUT", path)), view)[1])
    monkeypatch.setattr(agents_mod.api, "delete", lambda path: (calls.append(("DELETE", path)), view)[1])
    result = CliRunner().invoke(agents_mod.friends, ["--add", "Vortexia", "--remove", "Teli"])
    assert result.exit_code == 0, result.output
    assert calls == [("PUT", "/agents/Monkey/friends/Vortexia"), ("DELETE", "/agents/Monkey/friends/Teli")]
    assert "Vortexia" in result.output and "mutual" in result.output


# ── cross-machine friends (Name@env, over vortex-relay) ─────────────────────

def test_a_friend_on_another_machine_is_linked_and_listed_as_remote(app, monkeypatch):
    _main, client, tmp_path = app
    monkeypatch.setenv("VORTEXIA_ENV_NAME", "ba-mac")
    monkeypatch.setenv("VORTEXIA_RELAY_ENV_NAMES", "ba-mac,uy-mac")
    view = client.put("/agents/Monkey/friends/coach@uy-mac").json()
    assert view["friends"] == [{"name": "coach@uy-mac", "registered": True, "remote": "uy-mac", "inactive": False, "sessions": None, "mutual": None, "color": None}]
    assert _file(tmp_path, "Monkey")["friends"] == ["coach@uy-mac"]
    assert client.delete("/agents/Monkey/friends/coach@uy-mac").json()["friends"] == []


def test_a_remote_friend_on_this_machine_is_the_local_agent(app, monkeypatch):
    _main, client, tmp_path = app
    monkeypatch.setenv("VORTEXIA_ENV_NAME", "ba-mac")
    client.put("/agents/Monkey/friends/Teli@ba-mac")
    assert _file(tmp_path, "Monkey")["friends"] == ["Teli"]
    assert client.put("/agents/Monkey/friends/Ghost@ba-mac").status_code == 404


def test_remote_friend_refusals(app, monkeypatch):
    _main, client, _tmp = app
    monkeypatch.delenv("VORTEXIA_ENV_NAME", raising=False)
    assert client.put("/agents/Monkey/friends/coach@uy-mac").status_code == 400, "no vortex-relay here"
    monkeypatch.setenv("VORTEXIA_ENV_NAME", "ba-mac")
    monkeypatch.setenv("VORTEXIA_RELAY_ENV_NAMES", "ba-mac,uy-mac")
    assert client.put("/agents/Monkey/friends/coach@nowhere").status_code == 404, "unknown environment"
    assert client.put("/agents/Monkey/friends/@uy-mac").status_code == 422
    assert client.put("/agents/Monkey/friends/coach@").status_code == 422


def test_send_friends_reaches_remote_friends_by_their_relay_address(monkeypatch):
    from cli.commands import agents as agents_mod
    sent = []
    monkeypatch.setattr(agents_mod.api, "get", lambda path: {"friends": [{"name": "Vortexia", "registered": True}, {"name": "coach@uy-mac", "registered": True, "remote": "uy-mac"}]})
    monkeypatch.setattr(agents_mod.api, "post", lambda path, data=None, timeout=None: (sent.append(data), {"injected": True})[1])
    result = CliRunner().invoke(agents_mod.send, ["hola", "--to", "RelayRobotics", "--friends", "--from", "RelayRobotics"])
    assert result.exit_code == 0, result.output
    assert [d["to"] for d in sent] == ["Vortexia", "coach@uy-mac"]


# ── a friend's color: its own tone everywhere, this Mac or another ──────────

def test_a_local_friend_carries_the_color_in_its_own_file(app):
    _main, client, tmp_path = app
    assert client.patch("/agents/Vortexia/config", json={"color": "#3366cc"}).status_code == 200
    assert _file(tmp_path, "Vortexia")["color"] == "#3366cc"
    client.put("/agents/Monkey/friends/Vortexia")
    client.put("/agents/Monkey/friends/Teli")
    colors = {f["name"]: f["color"] for f in client.get("/agents/Monkey/friends").json()["friends"]}
    assert colors == {"Vortexia": "#3366cc", "Teli": None}, "no color written yet -> None, never a made-up default"


def test_a_config_color_must_be_hex(app):
    _main, client, _tmp = app
    for bad in ("blue", "#12345", "#gggggg", 7):
        assert client.patch("/agents/Vortexia/config", json={"color": bad}).status_code == 422, bad


def test_a_remote_friend_gets_its_color_from_the_relay_directory(app, monkeypatch):
    main, client, _tmp = app
    monkeypatch.setenv("VORTEXIA_ENV_NAME", "ba-mac")
    monkeypatch.setenv("VORTEXIA_RELAY_ENV_NAMES", "ba-mac,uy-mac")
    directory = [
        {"envName": "uy-mac", "agentName": "coach", "scopeText": "x", "color": "#aa5500"},
        {"envName": "ba-mac", "agentName": "billing", "scopeText": "x", "color": "#000000"},
        {"envName": "uy-mac", "agentName": "billing", "scopeText": "x", "color": "not-a-color"},
    ]
    main._on_relay_directory(json.dumps({"envName": "ba-mac", "entries": directory}).encode())
    for friend in ("coach@uy-mac", "billing@uy-mac", "sim@uy-mac"):
        client.put(f"/agents/Monkey/friends/{friend}")
    colors = {f["name"]: f["color"] for f in client.get("/agents/Monkey/friends").json()["friends"]}
    assert colors == {"coach@uy-mac": "#aa5500", "billing@uy-mac": None, "sim@uy-mac": None}, \
        "matched on name AND env; a malformed color is dropped; an agent the directory lacks has none"


def test_the_relay_directory_is_held_in_memory_so_the_panel_never_waits(app):
    """The friends view never opens a broker connection: a background subscriber keeps the
    retained directory current, and a malformed payload never wipes the last good copy."""
    main, client, _tmp = app
    main._on_relay_directory(json.dumps({"entries": [{"envName": "uy-mac", "agentName": "coach", "color": "#aa5500"}]}).encode())
    for junk in (b"not json", json.dumps({"entries": "x"}).encode(), json.dumps([1]).encode(), b"\xff"):
        main._on_relay_directory(junk)
    assert main._remote_color("coach", "uy-mac") == "#aa5500"
    assert main._remote_color("coach", "ba-mac") is None
