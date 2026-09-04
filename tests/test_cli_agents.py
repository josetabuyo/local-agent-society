"""
Regression test for the "swallowed SystemExit" bug in cli/commands/agents.py.

`cli.api.get`/`post`/etc. print an error and `sys.exit(1)` (raising SystemExit)
when the backend is unreachable or returns an HTTP error. `agent new` used to
catch that SystemExit around the locale lookup and silently fall back to
"en-US", so the command reported success (exit code 0) even though the
backend call actually failed. This test asserts the failure now propagates.
"""
from click.testing import CliRunner

from cli.commands import agents as agents_mod
from cli import api as api_mod


def test_agent_new_propagates_backend_failure(monkeypatch, tmp_path):
    """`las agent new` must exit non-zero if the backend locale lookup fails."""

    def fake_get(path):
        # Simulate cli.api.get's real behavior on a backend/HTTP error:
        # it prints an error and calls sys.exit(1), raising SystemExit.
        print("Error: backend not running. Try `las start`.")
        raise SystemExit(1)

    monkeypatch.setattr(api_mod, "get", fake_get)
    monkeypatch.setattr(agents_mod.api, "get", fake_get)

    runner = CliRunner()
    result = runner.invoke(
        agents_mod.new,
        ["testagent", "--voice", "Samantha", "--dir", str(tmp_path / "agentdir")],
    )

    # The command must NOT silently succeed with a fallback locale.
    assert result.exit_code != 0
    assert isinstance(result.exception, SystemExit)

    # It must not have gotten far enough to write a bogus .las-agent.json either.
    assert not (tmp_path / "agentdir" / ".las-agent.json").exists()


def test_widgets_all_skips_inactive_agents(monkeypatch):
    """`las widgets` is a bulk/auto reopen — an inactive agent must stay put
    away unless deliberately reactivated (`las widget NAME`, `las agent
    activate`, or the vortexia wake-enabled fallback), none of which go
    through this command."""
    monkeypatch.setattr(
        agents_mod.api,
        "get",
        lambda path: {
            "Active1": {"inactive": False},
            "Inactive1": {"inactive": True},
            "Active2": {},  # no "inactive" key at all -> must still open
        },
    )
    opened = []
    monkeypatch.setattr(
        agents_mod.subprocess, "run", lambda cmd, **kw: opened.append(cmd[-1])
    )

    runner = CliRunner()
    result = runner.invoke(agents_mod.widgets_all)

    assert result.exit_code == 0
    assert any("Active1" in url for url in opened)
    assert any("Active2" in url for url in opened)
    assert not any("Inactive1" in url for url in opened)


def test_agent_listen_exits_cleanly_when_vortexia_unreachable(monkeypatch):
    """`las agent listen` must fail soft (clear message, exit 1) — not hang or
    crash — when it can't find a vortexia-mqtt port in the registry. This is
    the live-delivery counterpart to `las agent poll`: it's meant to be run
    under Claude Code's Monitor tool (see .claude/skills/las-agent/SKILL.md),
    so a hang here would hang the whole session-start flow instead of just
    reporting "no live delivery available" and moving on.
    """
    monkeypatch.setattr(agents_mod.api, "get", lambda path: {})  # no vortexia-mqtt entry

    runner = CliRunner()
    result = runner.invoke(agents_mod.listen, ["testagent"])

    assert result.exit_code != 0
    assert "vortexia unreachable" in result.output.lower()
