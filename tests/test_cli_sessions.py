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
