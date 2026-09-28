"""`las agent sessions` and `send --session/--all-sessions` (docs/adr/0004 phase 2)."""
from click.testing import CliRunner

from cli.commands import agents as agents_mod
from cli.main import cli


def _spy(monkeypatch, view):
    gets, posts = [], []
    monkeypatch.setattr(agents_mod.api, "get", lambda path: (gets.append(path), view)[1])
    monkeypatch.setattr(agents_mod.api, "post", lambda path, data=None: (posts.append((path, data)), {"injected": True, "mode": "session" if data and data.get("session") else "all-sessions" if data and data.get("all_sessions") else "direct", **view})[1])
    return gets, posts


def test_sessions_lists_most_recent_first_with_the_default_marked(monkeypatch):
    view = {"agent": "Robo", "default": "shell-2", "sessions": [
        {"sid": "shell-2", "runtime": "shell", "pid": 2, "cwd": "/r", "lastActiveAt": 0, "default": True},
        {"sid": "claude-1", "runtime": "claude", "pid": 1, "cwd": "/r", "lastActiveAt": 0, "default": False},
    ]}
    _spy(monkeypatch, view)
    out = CliRunner().invoke(cli, ["agent", "sessions", "Robo"]).output.splitlines()
    assert out[0].startswith("* shell-2") and out[1].startswith("  claude-1")


def test_sessions_use_touches_by_id_or_runtime(monkeypatch):
    view = {"agent": "Robo", "default": "shell-2", "sessions": [
        {"sid": "shell-2", "runtime": "shell", "pid": 2, "cwd": "/r", "lastActiveAt": 0, "default": True},
        {"sid": "claude-1", "runtime": "claude", "pid": 1, "cwd": "/r", "lastActiveAt": 0, "default": False},
    ]}
    gets, posts = _spy(monkeypatch, view)
    assert CliRunner().invoke(cli, ["agent", "sessions", "Robo", "--use", "claude"]).exit_code == 0
    assert posts == [("/agents/Robo/sessions/claude-1/touch", {})]
    missing = CliRunner().invoke(cli, ["agent", "sessions", "Robo", "--use", "codex"])
    assert missing.exit_code == 1 and "no connected session" in missing.output


def test_send_session_and_all_sessions_flags_reach_the_backend(monkeypatch):
    gets, posts = _spy(monkeypatch, {})
    runner = CliRunner()
    assert runner.invoke(cli, ["agent", "send", "--to", "Robo", "--session", "shell", "ls", "--from", "Me"]).exit_code == 0
    assert runner.invoke(cli, ["agent", "send", "--to", "Robo", "--all-sessions", "hi", "--from", "Me"]).exit_code == 0
    assert posts[0] == ("/agents/send", {"message": "ls", "source": "agent", "from_agent": "Me", "to": "Robo", "session": "shell"})
    assert posts[1] == ("/agents/send", {"message": "hi", "source": "agent", "from_agent": "Me", "to": "Robo", "all_sessions": True})
    both = runner.invoke(cli, ["agent", "send", "--to", "Robo", "--session", "x", "--all-sessions", "hi"])
    assert both.exit_code != 0 and "exclusive" in both.output
    no_to = runner.invoke(cli, ["agent", "send", "--scope", "billing", "--session", "x", "hi"])
    assert no_to.exit_code != 0


def test_legacy_listen_stands_down_when_a_bridge_session_holds_the_mailbox(monkeypatch):
    """No fight with `las claude|codex|shell`: with a session registered, `listen` holds nothing and waits."""
    view = {"agent": "Robo", "default": "codex-1", "sessions": [{"sid": "codex-1", "runtime": "codex", "pid": 1, "cwd": "/r", "lastActiveAt": 0, "default": True}]}
    monkeypatch.setattr(agents_mod.api, "get", lambda path: view)
    slept = []

    def fake_sleep(s):
        slept.append(s)
        raise KeyboardInterrupt  # the Monitor/purge killing it, in test form

    monkeypatch.setattr(agents_mod.time, "sleep", fake_sleep)
    result = CliRunner().invoke(cli, ["agent", "listen", "Robo"])
    assert slept == [3600], "went to sleep instead of connecting as the mailbox consumer"
    assert "standing by without consuming anything" in result.output
    assert "las claude" in result.output

    monkeypatch.setattr(agents_mod.api, "get", lambda path: {"agent": "Robo", "default": None, "sessions": []} if path.endswith("/sessions") else {})
    agents_mod._legacy_listen_stand_down("Robo")  # no sessions: returns, the real consumer path would follow
