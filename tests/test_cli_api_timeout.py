"""cli.api._request must turn EVERY transport failure into the same clean
"print + SystemExit(1)" contract its callers rely on (tests/test_cli_commands.py,
`las claude`'s fail-soft presence step in cli/commands/bridge.py).

Regression: a backend that was up but starved — the Mac swapping, Kokoro
synthesis hogging the backend process — answered after the 5s read timeout.
requests raises ReadTimeout for that, which is a requests.Timeout, NOT a
ConnectionError, so it escaped _request as a raw traceback and `las claude`
died before ever exec'ing Claude (seen 2026-09-29)."""
from click.testing import CliRunner

import pytest
import requests

from cli import api as api_mod
from cli.commands import bridge as bridge_mod
from cli.main import cli


@pytest.mark.parametrize("exc", [requests.ReadTimeout, requests.ConnectTimeout, requests.Timeout])
def test_request_turns_a_timeout_into_a_clean_exit(monkeypatch, capsys, exc):
    def slow_post(url, json=None, timeout=None):
        assert timeout == api_mod.TIMEOUT_S
        raise exc("Read timed out. (read timeout=5)")

    monkeypatch.setattr(api_mod.requests, "post", slow_post)
    with pytest.raises(SystemExit) as info:
        api_mod.post("/agents/Robo/vortexia/register", {})
    assert info.value.code == 1
    out = capsys.readouterr().out
    assert "Traceback" not in out
    if exc is requests.ConnectTimeout:
        # Also a ConnectionError: nobody answered the socket at all, so the
        # "backend not running" wording stays right.
        assert "backend not running" in out
    else:
        assert "timed out" in out and "/agents/Robo/vortexia/register" in out


def test_request_still_reports_a_dead_backend_the_old_way(monkeypatch, capsys):
    def refused(url, timeout=None):
        raise requests.ConnectionError("Connection refused")

    monkeypatch.setattr(api_mod.requests, "get", refused)
    with pytest.raises(SystemExit):
        api_mod.get("/health")
    assert "backend not running" in capsys.readouterr().out


def test_las_claude_still_opens_when_the_backend_only_times_out(monkeypatch, tmp_path):
    """End to end through the real cli.api: the presence step fails soft on a
    timeout exactly as it does on a dead backend, and Claude is still exec'd."""
    monkeypatch.setenv("LAS_CLAUDE_CONFIG", str(tmp_path / "claude.json"))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(bridge_mod, "_las", lambda: "/Users/me/.local/bin/las")
    monkeypatch.setattr(bridge_mod, "_agent_name_from_cwd", lambda: "Robo")
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    calls = []
    monkeypatch.setattr(bridge_mod, "_exec", lambda argv: calls.append(argv))

    def slow_post(url, json=None, timeout=None):
        raise requests.ReadTimeout("Read timed out. (read timeout=5)")

    monkeypatch.setattr(api_mod.requests, "post", slow_post)

    result = CliRunner().invoke(cli, ["claude", "--no-widget", "--resume"])
    assert result.exit_code == 0, result.output
    assert "presence not published" in result.output
    assert calls == [["claude", bridge_mod.CLAUDE_CHANNEL_FLAG, bridge_mod.CLAUDE_CHANNEL_SERVER, "--resume"]]
