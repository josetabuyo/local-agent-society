"""The end-of-turn hook asks an agent for its closing report once, and only when it didn't speak."""
import json
from pathlib import Path

from cli import turn_hook as th


def agent_dir(tmp_path, locale="es-MX"):
    d = tmp_path / "Alpha"
    d.mkdir()
    (d / ".las-agent.json").write_text(json.dumps({"name": "Alpha", "locale": locale}))
    return d


def transcript(tmp_path, prompt):
    t = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "timestamp": "2026-11-27T10:00:00Z", "message": {"content": "old prompt"}},
        {"type": "user", "timestamp": "2026-11-27T10:05:00.000Z", "message": {"content": [{"type": "text", "text": prompt}]}},
        {"type": "assistant", "timestamp": "2026-11-27T10:05:05Z", "message": {"content": [{"type": "tool_use"}]}},
        {"type": "user", "timestamp": "2026-11-27T10:05:09Z", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
    ]
    t.write_text("\n".join(json.dumps(r) for r in rows))
    return t


def chat(*kinds):
    return lambda _url: {"messages": [{"kind": k} for k in kinds]}


def test_turn_without_speak_is_blocked_once(tmp_path):
    d = agent_dir(tmp_path)
    p = {"cwd": str(d / "sub"), "transcript_path": str(transcript(tmp_path, "fix the bug"))}
    (d / "sub").mkdir()
    got = th.claude_stop(p, fetch=chat("message"))
    assert got["decision"] == "block" and "Reportando" in got["reason"] and "--name Alpha" in got["reason"]
    assert th.claude_stop({**p, "stop_hook_active": True}, fetch=chat()) is None


def test_the_turn_starts_at_the_last_prompt_not_a_tool_result(tmp_path):
    seen = []
    th.claude_stop({"cwd": str(agent_dir(tmp_path)), "transcript_path": str(transcript(tmp_path, "go"))},
                   fetch=lambda url: seen.append(url) or {"messages": []})
    assert "after=1795773900000" in seen[0]


def test_a_turn_that_spoke_is_left_alone(tmp_path):
    p = {"cwd": str(agent_dir(tmp_path)), "transcript_path": str(transcript(tmp_path, "go"))}
    assert th.claude_stop(p, fetch=chat("message", "speak")) is None


def test_housekeeping_and_unknowns_never_nudge(tmp_path):
    d = agent_dir(tmp_path)
    for prompt in ['<channel source="las" kind="probe">[las-channel-probe] x</channel>', "<task-notification>done</task-notification>", th.NUDGE_MARK + " speak"]:
        assert th.claude_stop({"cwd": str(d), "transcript_path": str(transcript(tmp_path, prompt))}, fetch=chat()) is None
    t = str(transcript(tmp_path, "go"))
    assert th.claude_stop({"cwd": str(tmp_path / "nowhere"), "transcript_path": t}, fetch=chat()) is None   # not an agent
    def down(_url):
        raise OSError("backend down")
    assert th.claude_stop({"cwd": str(d), "transcript_path": t}, fetch=down) is None


def test_codex_turn_without_speak_is_nudged_through_its_session(tmp_path, monkeypatch):
    monkeypatch.setattr(th, "STATE_FILE", tmp_path / "state.json")
    d = agent_dir(tmp_path, locale="en-US")
    sent = []
    turn = {"type": "agent-turn-complete", "thread-id": "t1", "cwd": str(d), "input-messages": ["fix it"]}
    assert th.codex_notify(turn, fetch=chat(), send=sent.append, now=lambda: 1000.0)
    assert sent[0]["to"] == "Alpha" and sent[0]["session"] == "codex" and "Reporting" in sent[0]["message"]
    nudge_turn = {**turn, "input-messages": [sent[0]["message"]]}
    assert not th.codex_notify(nudge_turn, fetch=chat(), send=sent.append, now=lambda: 1010.0)
    assert not th.codex_notify(turn, fetch=chat("speak"), send=sent.append, now=lambda: 1020.0)
    assert len(sent) == 1


def test_installers_are_idempotent_and_keep_what_is_there(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}))
    assert th.ensure_claude_hook(s, las="/bin/las") and th.ensure_claude_hook(s, las="/bin/las")
    data = json.loads(s.read_text())
    assert data["model"] == "x" and len(data["hooks"]["Stop"]) == 2
    assert data["hooks"]["Stop"][1]["hooks"][0]["command"] == "/bin/las hook claude-stop"

    c = tmp_path / "codex" / "config.toml"
    c.parent.mkdir()
    c.write_text('model = "gpt"\n\n[projects."/x"]\ntrust_level = "trusted"\n')
    assert th.ensure_codex_notify(c, las="/bin/las") and th.ensure_codex_notify(c, las="/bin/las")
    text = c.read_text()
    assert text.count("notify =") == 1 and text.index("notify =") < text.index("[projects")
    other = tmp_path / "codex" / "other.toml"
    other.write_text('notify = ["my-notifier"]\n')
    assert not th.ensure_codex_notify(other, las="/bin/las") and "my-notifier" in other.read_text()
