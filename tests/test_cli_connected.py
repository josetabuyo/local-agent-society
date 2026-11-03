"""`las <command…>` (docs/adr/0006): a command connected to an agent, no terminal, one run per message."""
from datetime import datetime

from click.testing import CliRunner

import cli.connected as c


def test_log_paths_are_per_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "LOG_DIR", tmp_path)
    assert c.new_log_path("Robo", datetime(2026, 11, 3, 9, 0, 0)).name == "Robo-20261103-090000.log"


def test_connect_spawns_a_detached_exec_bridge_with_the_text_as_an_argument(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(c, "STARTUP_WAIT_S", 0)
    seen = {}

    class P:
        pid, returncode = 42, None
        def poll(self):
            return None

    monkeypatch.setattr(c, "spawn_detached", lambda argv, *, cwd, log_path, env: (seen.update(argv=argv, cwd=cwd, env=env), P())[1])
    pid, log = c.connect("Robo", tmp_path, "pulpo las", locale="es-AR", sessions=lambda n: [])
    argv = seen["argv"]
    assert pid == 42 and argv[2:5] == ["exec", "--agent", "Robo"]
    assert argv[argv.index("--exec") + 1] == "pulpo las" and argv[argv.index("--text-as") + 1] == "arg"
    assert argv[argv.index("--log") + 1] == str(log)
    assert seen["cwd"] == tmp_path and seen["env"]["LAS_LOCALE"] == "es-AR"


def test_las_any_program_connects_it_and_unknown_words_still_error(monkeypatch):
    import cli.main as m
    import cli.commands.bridge as b
    ran = []
    monkeypatch.setattr(m.shutil, "which", lambda w: "/bin/" + w if w == "pulpo" else None)
    monkeypatch.setattr(b, "run_connected", lambda argv: ran.append(argv))
    assert CliRunner().invoke(m.cli, ["pulpo", "las"]).exit_code == 0
    assert ran == [["pulpo", "las"]]
    assert CliRunner().invoke(m.cli, ["nonexistent-xyz"]).exit_code != 0
    assert m.cli.get_command(None, "speak") is not None, "real subcommands win over PATH programs"


def test_run_connected_quotes_the_command_line(tmp_path, monkeypatch):
    import cli.commands.bridge as b
    monkeypatch.setattr(b, "resolve_agent_name", lambda n: "Robo")
    monkeypatch.setattr(c, "agent_dir_of", lambda n: tmp_path)
    seen = {}
    monkeypatch.setattr(c, "connect", lambda name, agent_dir, command, **kw: (seen.update(command=command), (7, tmp_path / "l.log"))[1])
    b.run_connected(["pulpo", "luganense", "two words"])
    assert seen["command"] == "pulpo luganense 'two words'"


def test_las_attach_runs_the_same_in_this_terminal(monkeypatch):
    import cli.commands.bridge as b
    seen = {}
    monkeypatch.setattr(b, "resolve_agent_name", lambda n: "Robo")
    monkeypatch.setattr(b, "_chain", lambda name: None)
    monkeypatch.setattr(b, "_sign_terminal", lambda name, runtime: seen.update(runtime=runtime))
    monkeypatch.setattr(b, "_exec", lambda argv: seen.update(argv=argv))
    CliRunner().invoke(b.attach_cmd, ["pulpo", "las"])
    argv = seen["argv"]
    assert seen["runtime"] == "pulpo" and argv[2:5] == ["exec", "--agent", "Robo"]
    assert argv[argv.index("--text-as") + 1] == "arg" and "--log" not in argv
