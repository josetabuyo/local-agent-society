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

    # It must not have gotten far enough to write a bogus .agent.json either.
    assert not (tmp_path / "agentdir" / ".agent.json").exists()
