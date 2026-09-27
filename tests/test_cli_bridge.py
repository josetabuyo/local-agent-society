"""`las bridge` and `las claude` are thin launchers over bridge/bin/las-bridge.js
(docs/adr/0004): these tests pin the argv they hand to the Node bridge, the
research-preview channel flag `las claude` adds, the status file contract
the /las-agent skill relies on, and the idempotent ~/.claude.json edit."""
import json
import os

from click.testing import CliRunner

from cli.commands import bridge as bridge_mod
from cli.main import cli


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(bridge_mod, "_exec", lambda argv: calls.append(argv))
    monkeypatch.setattr(bridge_mod, "_node", lambda: "/usr/local/bin/node")
    return calls


def test_each_sink_launches_the_node_bridge_with_agent_and_sink(monkeypatch):
    calls = _capture(monkeypatch)
    runner = CliRunner()
    assert runner.invoke(cli, ["bridge", "claude", "Robo"]).exit_code == 0
    assert runner.invoke(cli, ["bridge", "stdout", "Robo", "--port", "9012"]).exit_code == 0
    assert runner.invoke(cli, ["bridge", "shell", "Robo", "--yes", "--all"]).exit_code == 0
    assert runner.invoke(cli, ["bridge", "exec", "Robo", "--exec", "codex exec -", "--intercept-url", "http://localhost:9999/decide"]).exit_code == 0
    bin_path = str(bridge_mod.BRIDGE_BIN)
    assert calls[0] == ["/usr/local/bin/node", bin_path, "claude", "--agent", "Robo"]
    assert calls[1] == ["/usr/local/bin/node", bin_path, "stdout", "--agent", "Robo", "--port", "9012"]
    assert calls[2] == ["/usr/local/bin/node", bin_path, "shell", "--agent", "Robo", "--yes", "--all"]
    assert calls[3] == ["/usr/local/bin/node", bin_path, "exec", "--agent", "Robo", "--exec", "codex exec -", "--intercept-url", "http://localhost:9999/decide"]


def test_exec_sink_requires_a_command(monkeypatch):
    calls = _capture(monkeypatch)
    result = CliRunner().invoke(cli, ["bridge", "exec", "Robo"])
    assert result.exit_code != 0
    assert "--exec" in result.output
    assert calls == []


def test_las_claude_adds_the_channel_flag_and_passes_everything_else_through(monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    result = CliRunner().invoke(cli, ["claude", "--resume", "--model", "opus"])
    assert result.exit_code == 0, result.output
    assert calls == [["claude", bridge_mod.CLAUDE_CHANNEL_FLAG, bridge_mod.CLAUDE_CHANNEL_SERVER, "--resume", "--model", "opus"]]
    assert bridge_mod.CLAUDE_CHANNEL_FLAG == "--dangerously-load-development-channels"
    assert bridge_mod.CLAUDE_CHANNEL_SERVER == "server:las"


def test_status_exit_code_is_the_skill_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge_mod, "SESSION_DIR", tmp_path)
    runner = CliRunner()
    absent = runner.invoke(cli, ["bridge", "status", "Robo"])
    assert absent.exit_code == 1
    assert "no bridge running" in absent.output

    (tmp_path / "bridge-Robo.json").write_text(json.dumps({"agent": "Robo", "sink": "claude-channel", "pid": os.getpid(), "armed": False, "delivered": 0}))
    waiting = runner.invoke(cli, ["bridge", "status", "Robo"])
    assert waiting.exit_code == 1
    assert "waiting" in waiting.output

    (tmp_path / "bridge-Robo.json").write_text(json.dumps({"agent": "Robo", "sink": "claude-channel", "pid": os.getpid(), "armed": True, "delivered": 3}))
    armed = runner.invoke(cli, ["bridge", "status", "Robo"])
    assert armed.exit_code == 0
    assert "armed, 3 delivered" in armed.output

    (tmp_path / "bridge-Robo.json").write_text(json.dumps({"agent": "Robo", "sink": "claude-channel", "pid": 999999999, "armed": True}))
    dead = runner.invoke(cli, ["bridge", "status", "Robo"])
    assert dead.exit_code == 1, "a stale status file from a dead process must not read as delivering"


def test_install_registers_the_mcp_server_idempotently_and_uninstall_removes_it(monkeypatch, tmp_path):
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}))
    monkeypatch.setenv("LAS_CLAUDE_CONFIG", str(config))
    monkeypatch.setattr(bridge_mod, "_node", lambda: "/usr/local/bin/node")
    runner = CliRunner()

    first = runner.invoke(cli, ["bridge", "install"])
    assert first.exit_code == 0, first.output
    data = json.loads(config.read_text())
    assert data["theme"] == "dark" and "other" in data["mcpServers"], "other keys untouched"
    assert data["mcpServers"]["las"] == {"command": "/usr/local/bin/node", "args": [str(bridge_mod.BRIDGE_BIN), "claude"]}
    assert "registered" in first.output and "las claude" in first.output

    second = runner.invoke(cli, ["bridge", "install"])
    assert "already registered" in second.output
    assert json.loads(config.read_text()) == data

    gone = runner.invoke(cli, ["bridge", "install", "--uninstall"])
    assert gone.exit_code == 0
    assert "las" not in json.loads(config.read_text())["mcpServers"]

    config.write_text("{not json")
    broken = runner.invoke(cli, ["bridge", "install"])
    assert broken.exit_code == 1 and "not touching" in broken.output
    assert config.read_text() == "{not json"


# ── one command per runtime, chaining everything the session needs ────────────

def _chain_spies(monkeypatch, tmp_path, agent="Robo"):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(bridge_mod, "_agent_name_from_cwd", lambda: agent)
    monkeypatch.setattr(bridge_mod, "resolve_agent_name", lambda name, **kw: name or agent)
    config = tmp_path / ".claude.json"
    monkeypatch.setenv("LAS_CLAUDE_CONFIG", str(config))
    posts = []
    monkeypatch.setattr(bridge_mod.api, "post", lambda path, data=None: (posts.append(path), {"registered": True})[1])
    opened = []
    monkeypatch.setattr(bridge_mod.subprocess, "run", lambda argv, **kw: opened.append(argv))
    monkeypatch.setattr(bridge_mod.sys, "platform", "darwin")
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    return calls, config, posts, opened


def test_las_claude_chains_mcp_registration_presence_and_widget_then_execs(monkeypatch, tmp_path):
    calls, config, posts, opened = _chain_spies(monkeypatch, tmp_path)
    result = CliRunner().invoke(cli, ["claude", "--resume"])
    assert result.exit_code == 0, result.output
    assert json.loads(config.read_text())["mcpServers"]["las"]["args"][-1] == "claude", "MCP server registered without a separate install step"
    assert posts == ["/agents/Robo/vortexia/register"], "presence published"
    assert opened == [["open", "localagentsociety://Robo?action=reopen"]], "widget brought to this Space"
    assert calls == [["claude", bridge_mod.CLAUDE_CHANNEL_FLAG, bridge_mod.CLAUDE_CHANNEL_SERVER, "--resume"]]


def test_las_claude_outside_an_agent_folder_skips_the_chain_but_still_passes_the_flag(monkeypatch, tmp_path):
    calls, config, posts, opened = _chain_spies(monkeypatch, tmp_path, agent=None)
    assert CliRunner().invoke(cli, ["claude"]).exit_code == 0
    assert not config.exists() and posts == [] and opened == []
    assert calls == [["claude", bridge_mod.CLAUDE_CHANNEL_FLAG, bridge_mod.CLAUDE_CHANNEL_SERVER]]


def test_chain_fails_soft_when_the_backend_is_down(monkeypatch, tmp_path):
    calls, config, posts, opened = _chain_spies(monkeypatch, tmp_path)

    def down(path, data=None):
        print("Error: backend not running. Try `las start`.")
        raise SystemExit(1)

    monkeypatch.setattr(bridge_mod.api, "post", down)
    result = CliRunner().invoke(cli, ["claude", "--no-widget"])
    assert result.exit_code == 0, "a dead backend must not stop the session from opening"
    assert "presence not published" in result.output
    assert opened == [], "--no-widget honored"
    assert len(calls) == 1


def test_las_codex_and_las_shell_chain_then_launch_their_sinks(monkeypatch, tmp_path):
    calls, config, posts, opened = _chain_spies(monkeypatch, tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli, ["codex"]).exit_code == 0
    assert runner.invoke(cli, ["shell", "--yes"]).exit_code == 0
    monkeypatch.setenv("LAS_CODEX_CMD", "my-router --stdin")
    assert runner.invoke(cli, ["codex", "--no-widget"]).exit_code == 0
    bin_path = str(bridge_mod.BRIDGE_BIN)
    assert calls[0] == ["/usr/local/bin/node", bin_path, "exec", "--agent", "Robo", "--exec", "codex exec -"]
    assert calls[1] == ["/usr/local/bin/node", bin_path, "shell", "--agent", "Robo", "--yes"]
    assert calls[2] == ["/usr/local/bin/node", bin_path, "exec", "--agent", "Robo", "--exec", "my-router --stdin"]
    assert posts == ["/agents/Robo/vortexia/register"] * 3
    assert len(opened) == 2, "two widget reopens: the third run passed --no-widget"


def test_las_codex_refuses_clearly_when_codex_is_missing(monkeypatch, tmp_path):
    calls, *_ = _chain_spies(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: None if name == "codex" else f"/usr/local/bin/{name}")
    result = CliRunner().invoke(cli, ["codex"])
    assert result.exit_code == 1 and "codex not found" in result.output
    assert calls == []
