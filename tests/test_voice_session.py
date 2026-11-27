"""Voice sessions (docs/adr/0008): Claude/Codex with no terminal, one conversation across messages."""
import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

import cli.voice_session as v


class Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def recorder(result):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return result(argv) if callable(result) else result
    return run, calls


def test_claude_first_turn_creates_the_conversation_and_later_turns_resume_it(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    run, calls = recorder(Done("Listo, hecho."))
    out = v.run_turn("claude", "c0nv", "arreglá el test", name="Robo", locale="es-MX", cwd=str(tmp_path), run=run)
    argv, kw = calls[-1]
    assert out == "Listo, hecho."
    assert argv[argv.index("--session-id") + 1] == "c0nv" and argv[-1] == "arreglá el test"
    assert "--resume" not in argv and argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert "Spanish" in argv[argv.index("--append-system-prompt") + 1]
    assert kw["env"][v.VOICE_ENV] == "1" and kw["cwd"] == str(tmp_path)
    (cfg / "projects" / "-x").mkdir(parents=True)
    (cfg / "projects" / "-x" / "c0nv.jsonl").write_text("{}\n")
    v.run_turn("claude", "c0nv", "y ahora?", name="Robo", locale="es-MX", cwd=str(tmp_path), run=run)
    argv, _ = calls[-1]
    assert argv[argv.index("--resume") + 1] == "c0nv" and "--session-id" not in argv


def test_claude_account_uses_its_own_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(v.Path, "home", lambda: tmp_path)
    run, calls = recorder(Done("ok"))
    v.run_turn("claude", "c1", "hi", name="Robo", locale="en-US", cwd=str(tmp_path), account="relay", run=run)
    assert calls[-1][1]["env"]["CLAUDE_CONFIG_DIR"] == str(tmp_path / ".claude-relay")


def codex_out(thread, text):
    return "\n".join(json.dumps(e) for e in [
        {"type": "thread.started", "thread_id": thread}, {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "thinking"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
        {"type": "turn.completed"}])


def test_codex_keeps_the_thread_it_was_given_and_resumes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "VOICE_DIR", tmp_path / "voice")
    run, calls = recorder(Done(codex_out("th-1", "Hecho.")))
    assert v.run_turn("codex", "c2", "hola", name="Robo", locale="es-MX", cwd="/w", run=run) == "Hecho."
    argv, _ = calls[-1]
    assert argv[:4] == ["codex", "exec", "-C", "/w"] and argv[-1] == "hola" and "--yolo" in argv
    assert any(a.startswith("developer_instructions=") for a in argv)
    assert v.codex_thread_file("c2").read_text() == "th-1"
    v.run_turn("codex", "c2", "seguí", name="Robo", locale="es-MX", cwd="/w", run=run)
    assert calls[-1][0][:4] == ["codex", "exec", "resume", "th-1"]


def test_a_failed_turn_is_said_not_swallowed(tmp_path):
    run, _ = recorder(Done("", 1, "boom\nfatal: not logged in"))
    out = v.run_turn("codex", "c3", "x", name="R", locale="es-MX", cwd=str(tmp_path), run=run)
    assert out.startswith("No pude completar") and "not logged in" in out

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)
    assert "couldn't finish" in v.run_turn("claude", "c4", "x", name="R", locale="en-US", cwd=str(tmp_path), run=slow)


def test_turn_command_is_what_the_detached_session_runs():
    assert v.turn_command("/bin/las", "claude", "abc", "relay") == "/bin/las voice-turn claude abc --account relay"


def test_voice_turns_never_get_the_closing_report_nudge(monkeypatch, tmp_path):
    import cli.turn_hook as h
    monkeypatch.setenv(v.VOICE_ENV, "1")
    assert h.claude_stop({"cwd": str(tmp_path)}) is None
    assert h.claude_prompt({"prompt": "hola", "cwd": str(tmp_path)}) is False
    assert h.codex_notify({"type": "agent-turn-complete"}) is False


def test_headless_flags_start_a_voice_session(monkeypatch):
    import cli.main as m
    import cli.commands.bridge as b
    seen = []
    monkeypatch.setattr(b, "start_voice_session", lambda runtime, **kw: seen.append((runtime, kw)))
    for args, want in ((["claude", "--headless"], ("claude", None)), (["claudeRelay", "--headless"], ("claude", "relay")),
                       (["codex", "--headless"], ("codex", None))):
        r = CliRunner().invoke(m.cli, args)
        assert r.exit_code == 0, r.output
        assert (seen[-1][0], seen[-1][1].get("account")) == want


def test_start_voice_session_connects_names_it_and_takes_the_mic(tmp_path, monkeypatch):
    import cli.commands.bridge as b
    import cli.connected as c
    (tmp_path / ".las-agent.json").write_text(json.dumps({"name": "Robo", "locale": "es-MX"}))
    monkeypatch.setattr(b.shutil, "which", lambda w: "/bin/" + w)
    monkeypatch.setattr(b, "resolve_agent_name", lambda n: "Robo")
    monkeypatch.setattr(b, "_chain", lambda name, widget=True: None)
    seen, posts = {}, []
    monkeypatch.setattr(c, "connect", lambda name, d, command, **kw: (seen.update(command=command, d=d, **kw), (99, tmp_path / "l.log"))[1])
    monkeypatch.setattr(b.api, "get", lambda path: {"sessions": [{"sid": "claude-x", "pid": 99}]})
    monkeypatch.setattr(b.api, "post", lambda path, body: posts.append(path))
    out = b.start_voice_session("claude", cwd=str(tmp_path))
    assert " voice-turn claude " in seen["command"] and seen["runtime"] == "claude"
    assert seen["title"] == "sesión de voz, sin terminal" and seen["d"] == Path(tmp_path)
    assert posts == ["/agents/Robo/sessions/claude-x/touch"] and out["sid"] == "claude-x"
