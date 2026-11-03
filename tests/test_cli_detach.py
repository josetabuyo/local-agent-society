"""`las detach` (docs/adr/0006): the CLI side of a session with no terminal."""
from datetime import datetime

from click.testing import CliRunner

import cli.commands.detach as d


def test_log_paths_are_per_agent_and_the_latest_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "LOG_DIR", tmp_path)
    a = d.new_log_path("Robo", datetime(2026, 11, 3, 9, 0, 0))
    b = d.new_log_path("Robo", datetime(2026, 11, 3, 10, 0, 0))
    assert a.name == "Robo-20261103-090000.log"
    for p in (a, b, tmp_path / "Other-20261104-000000.log"):
        p.write_text("x")
    assert d.latest_log("Robo") == b
    assert d.latest_log("Nobody") is None


def test_open_without_a_command_suggests_one_and_starts_nothing(tmp_path, monkeypatch):
    (tmp_path / ".las-agent.json").write_text('{"name": "Robo"}')
    monkeypatch.setattr(d, "resolve_agent_name", lambda n: "Robo")
    monkeypatch.setattr(d.api, "get", lambda path: {"Robo": {"path": str(tmp_path)}})
    monkeypatch.setattr(d, "spawn_detached", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not spawn")))
    res = CliRunner().invoke(d.detach_cmd, [])
    assert res.exit_code == 1 and d.SUGGESTED_COMMAND in res.output


def test_open_saves_the_command_and_spawns_the_proc_bridge_detached(tmp_path, monkeypatch):
    (tmp_path / ".las-agent.json").write_text('{"name": "Robo", "locale": "es-AR"}')
    monkeypatch.setattr(d, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(d, "resolve_agent_name", lambda n: "Robo")
    monkeypatch.setattr(d, "STARTUP_WAIT_S", 0)
    monkeypatch.setattr(d.api, "get", lambda path: {"Robo": {"path": str(tmp_path)}})
    seen = {}

    class P:
        pid, returncode = 42, None
        def poll(self):
            return None

    def spawn(argv, *, cwd, log_path, env):
        seen.update(argv=argv, cwd=cwd, env=env)
        return P()

    monkeypatch.setattr(d, "spawn_detached", spawn)
    res = CliRunner().invoke(d.detach_cmd, ["--cmd", "pulpo agent run"])
    assert res.exit_code == 0, res.output
    assert '"detached"' in (tmp_path / ".las-agent.json").read_text() and "pulpo agent run" in (tmp_path / ".las-agent.json").read_text()
    argv = seen["argv"]
    assert argv[2:5] == ["proc", "--agent", "Robo"] and argv[argv.index("--exec") + 1] == "pulpo agent run"
    assert seen["cwd"] == tmp_path and seen["env"]["LAS_LOCALE"] == "es-AR"


def test_las_any_program_runs_it_connected_and_unknown_words_still_error(monkeypatch):
    """`las pulpo agent run`: a first word that is no subcommand but a program on PATH runs connected."""
    import cli.main as m
    import cli.commands.bridge as b
    ran = []
    monkeypatch.setattr(m.shutil, "which", lambda w: "/bin/" + w if w == "pulpo" else None)
    monkeypatch.setattr(b, "run_connected", lambda argv: ran.append(argv))
    res = CliRunner().invoke(m.cli, ["pulpo", "agent", "run", "--yes"])
    assert res.exit_code == 0, res.output
    assert ran == [["pulpo", "agent", "run", "--yes"]]
    assert CliRunner().invoke(m.cli, ["nonexistent-xyz"]).exit_code != 0
    assert m.cli.get_command(None, "speak") is not None, "real subcommands win over PATH programs"


def test_run_connected_execs_the_proc_bridge_with_the_whole_command_line(monkeypatch):
    import cli.commands.bridge as b
    seen = {}
    monkeypatch.setattr(b, "resolve_agent_name", lambda n: "Robo")
    monkeypatch.setattr(b, "_chain", lambda name: None)
    monkeypatch.setattr(b, "_sign_terminal", lambda name, runtime: seen.update(runtime=runtime))
    monkeypatch.setattr(b, "_exec", lambda argv: seen.update(argv=argv))
    b.run_connected(["pulpo", "agent", "run", "two words"])
    assert seen["runtime"] == "pulpo"
    argv = seen["argv"]
    assert argv[2:5] == ["proc", "--agent", "Robo"] and argv[argv.index("--exec") + 1] == "pulpo agent run 'two words'"
    assert "--log" not in argv, "a terminal session, not a detached one"
