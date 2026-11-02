"""`las local` — the local conversational agent (cli/local_agent.py), with fake models."""
import io
import json

from cli import local_agent as la


def _tools(calls):
    return [
        la.Tool("list_agents", "who is online", {"type": "object", "properties": {}},
                lambda: calls.append(("list_agents",)) or "Pulpo: claude, local"),
        la.Tool("run_shell", "run a command", {"type": "object", "properties": {"command": {"type": "string"}}},
                lambda command: calls.append(("run_shell", command)) or "ok", confirm=True),
    ]


def _answer(text):
    msg = {"role": "assistant", "content": text}
    return {"type": "answer", "messages": [msg], "message": msg, "model": "qwen3.5:4b"}


def _calls(*calls):
    msg = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]}
    return {"type": "tool_calls", "messages": [msg], "message": msg}


class FakeFlow:
    """Pulpo's las-local flow: returns scripted steps in order; records each request."""
    def __init__(self, *steps):
        self.steps = list(steps)
        self.seen = []

    def __call__(self, data):
        self.seen.append(json.loads(json.dumps(data)))
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def _agent(step, calls=None, skills=(), confirm=lambda p, o: True):
    return la.LocalAgent(name="Pulpo", agent_dir="/tmp", tools=_tools(calls if calls is not None else []),
                         skills=list(skills), step=step, confirm=confirm)


def test_a_turn_sends_the_whole_conversation_tools_and_skills_and_runs_the_asked_tool():
    calls = []
    flow = FakeFlow(_calls(("list_agents", {})), _answer("Pulpo está conectado"))
    skill = la.Skill("deploy-web", "how to deploy the web", "npx vercel --prod")
    answer = _agent(flow, calls, skills=[skill]).handle(la.Turn("¿quién está?", "human"))
    assert answer == "Pulpo está conectado" and calls == [("list_agents",)]
    first, second = flow.seen
    assert first["agent_name"] == "Pulpo" and first["messages"] == [{"role": "user", "content": "[dictated by the human] ¿quién está?"}]
    assert [t["function"]["name"] for t in first["tools"]] == ["list_agents", "run_shell"]
    assert first["skills"] == [{"name": "deploy-web", "description": "how to deploy the web", "body": "npx vercel --prod"}]
    # the step's own messages, then the tool result, go back on the next step
    assert second["messages"][1]["tool_calls"][0]["function"]["name"] == "list_agents"
    assert second["messages"][2] == {"role": "tool", "tool_name": "list_agents", "content": "Pulpo: claude, local"}


def test_string_json_arguments_are_accepted():
    calls = []
    _agent(FakeFlow(_calls(("run_shell", '{"command": "ls"}')), _answer("ok")), calls).handle(la.Turn("ls"))
    assert calls == [("run_shell", "ls")]


def test_pulpo_down_or_a_model_error_is_said_not_raised():
    down = _agent(FakeFlow(la.StepError("Pulpo unreachable"))).handle(la.Turn("hola"))
    assert down.startswith("(no answer:") and "unreachable" in down
    err = _agent(FakeFlow({"type": "error", "messages": [], "error": "ollama down"})).handle(la.Turn("hola"))
    assert err == "(no answer: ollama down)"


def test_pulpo_step_posts_the_contract_and_rejects_odd_answers(monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen["url"], seen["body"], seen["timeout"] = req.full_url, json.loads(req.data), timeout
        return Resp(json.dumps({"run_id": "inline_1", "response": _answer("hola")}).encode())
    monkeypatch.setattr(la.urllib.request, "urlopen", urlopen)
    assert la.pulpo_step({"messages": []})["type"] == "answer"
    assert seen["url"] == la.FLOW_URL and seen["body"]["wait"] is True and seen["body"]["timeout_ms"] == la.STEP_TIMEOUT_MS
    assert seen["timeout"] > la.STEP_TIMEOUT_MS / 1000   # the flow's own 504 arrives first
    monkeypatch.setattr(la.urllib.request, "urlopen", lambda req, timeout: Resp(b'{"response": {"type": "maybe"}}'))
    import pytest
    with pytest.raises(la.StepError):
        la.pulpo_step({"messages": []})


def test_declined_confirmation_does_not_run_the_tool():
    calls = []
    flow = FakeFlow(_calls(("run_shell", {"command": "rm -rf x"})), _answer("no lo corrí"))
    _agent(flow, calls, confirm=lambda p, o: False).handle(la.Turn("borrá x"))
    assert calls == []
    assert flow.seen[1]["messages"][-1]["content"] == "the human declined to run this"


def test_tool_rounds_are_capped():
    flow = FakeFlow(*[_calls(("list_agents", "{}"))] * (la.MAX_TOOL_ROUNDS + 1))
    answer = _agent(flow).handle(la.Turn("x"))
    assert "too many tool calls" in answer


def test_history_is_bounded_and_tool_chatter_dropped():
    agent = _agent(FakeFlow(*[_answer(str(i)) for i in range(20)]))
    for i in range(20):
        agent.handle(la.Turn(f"m{i}"))
    assert len(agent.history) == la.HISTORY_TURNS
    assert {m["role"] for m in agent.history} == {"user", "assistant"}


def test_think_blocks_are_stripped():
    assert la._strip_think("<think>hmm</think> Hola") == "Hola"


def test_skill_parsing_needs_a_description(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "a.md").write_text("---\nname: alpha\ndescription: does A\n---\nbody A")
    (d / "b.md").write_text("no front matter")
    skills = la.load_skills([d])
    assert [(s.name, s.description, s.body) for s in skills] == [("alpha", "does A", "body A")]


def test_file_tools_stay_inside_the_agent_folder(tmp_path):
    (tmp_path / "x.txt").write_text("hi")
    tools = {t.name: t for t in la.default_tools("Pulpo", str(tmp_path))}
    assert tools["read_file"].run(path="x.txt") == "hi"
    assert tools["read_file"].run(path="../../etc/passwd").startswith("error:")
    assert tools["run_shell"].confirm


def test_envelopes_become_turns():
    assert la.envelope_to_turn({"kind": "probe", "text": "x"}, "Pulpo") is None
    assert la.envelope_to_turn({"kind": "cc", "text": "x"}, "Pulpo") is None
    assert la.envelope_to_turn({"kind": "title-request", "text": "x"}, "Pulpo") is None
    assert la.envelope_to_turn({"text": la.MIC_SELFTEST_PING}, "Pulpo") == "selftest"
    mic = la.envelope_to_turn({"from": "Pulpo", "source": "human", "text": "hola"}, "Pulpo")
    assert (mic.origin, mic.sender) == ("human", None)
    msg = la.envelope_to_turn({"from": "Wavi", "source": "agent", "text": "che"}, "Pulpo")
    assert (msg.origin, msg.sender) == ("agent", "Wavi")


def test_runtime_answers_the_terminal_and_exits(monkeypatch):
    sent = []
    monkeypatch.setattr(la, "_sh", lambda argv, **k: sent.append(argv) or "")
    out = io.StringIO()
    agent = _agent(FakeFlow(_answer("¡hola!")))
    rt = la.LocalRuntime(agent, bridge_argv=None, stdin=io.StringIO("hola\n/exit\n"), out=out)
    assert rt.run() == 0
    assert "Pulpo › ¡hola!" in out.getvalue()
    assert sent == []   # terminal turns are only printed


def test_runtime_replies_to_the_sending_agent(monkeypatch):
    sent = []
    monkeypatch.setattr(la, "_sh", lambda argv, **k: sent.append(argv) or "")
    agent = _agent(FakeFlow(_answer("listo")))
    rt = la.LocalRuntime(agent, bridge_argv=None, las="las", out=io.StringIO())
    turn = la.envelope_to_turn({"from": "Wavi", "source": "agent", "text": "hacé algo"}, "Pulpo")
    rt.deliver(turn, agent.handle(turn))
    assert sent == [["las", "agent", "send", "--to", "Wavi", "--from", "Pulpo", la.AUTO_REPLY_MARK + "listo"]]


def test_sessions_listing_is_flattened_per_agent():
    raw = ('LocalModels\n  claude-31453-820a3a          claude      "Guardados IG"  *default\n'
           'Pulpo\n  claude-75682-22ce71          claude      "Nodo Jev"  *default\n  local-1  local\n')
    assert la.flatten_sessions(raw).splitlines() == [
        'agent LocalModels: one claude terminal open — working on "Guardados IG"',
        'agent Pulpo: one claude terminal open — working on "Nodo Jev"',
        'agent Pulpo: one local terminal open',
    ]


def test_yes_never_covers_another_agents_message():
    from cli.commands.local import confirm_tool
    asked = []
    no = lambda p: asked.append(p) or False
    assert confirm_tool("run_shell ls", "terminal", True, ask=no) is True
    assert confirm_tool("run_shell ls", "human", True, ask=no) is True
    assert confirm_tool("run_shell ls", "agent", True, ask=no) is False
    assert confirm_tool("run_shell ls", "terminal", False, ask=no) is False
    assert len(asked) == 2


def test_tool_confirmation_sees_the_turns_origin():
    seen = []
    agent = _agent(FakeFlow(_calls(("run_shell", {"command": "ls"})), _answer("ok")),
                   confirm=lambda p, o: seen.append(o) or False)
    agent.handle(la.Turn("ls", "agent", "Wavi"))
    assert seen == ["agent"]


def test_automatic_replies_are_never_answered():
    assert la.envelope_to_turn({"from": "Wavi", "source": "agent", "text": la.AUTO_REPLY_MARK + "listo"}, "Pulpo") is None


def test_replies_to_one_sender_are_capped_per_minute():
    rt = la.LocalRuntime(_agent(FakeFlow()), bridge_argv=None, out=io.StringIO())
    assert [rt.may_reply("Wavi", now=t) for t in range(la.REPLIES_PER_MINUTE + 1)] == [True] * la.REPLIES_PER_MINUTE + [False]
    assert rt.may_reply("Teli", now=5) is True
    assert rt.may_reply("Wavi", now=100) is True


def test_spoken_answer_and_title_are_never_cut(monkeypatch):
    sent = []
    monkeypatch.setattr(la, "_sh", lambda argv, **k: sent.append(argv) or "")
    long = "x" * 900
    agent = _agent(FakeFlow(_answer("Un título bastante más largo que treinta y cuatro caracteres")))
    rt = la.LocalRuntime(agent, bridge_argv=None, out=io.StringIO())
    rt.deliver(la.Turn("hola", "human"), long)
    assert sent[-1][2] == long
    rt.last_topic = "algo"
    rt.answer_title_request({"text": "las agent title ... --session local-1-abc"})
    assert sent[-1][3] == "Un título bastante más largo que treinta y cuatro caracteres"
    assert sent[-1][-2:] == ["--session", "local-1-abc"]


def test_title_falls_back_to_the_whole_topic(monkeypatch):
    rt = la.LocalRuntime(_agent(FakeFlow(la.StepError("Pulpo down"))), bridge_argv=None, out=io.StringIO())
    rt.last_topic = "una consulta larga sobre los puertos de la base de datos local"
    assert rt.make_title() == rt.last_topic
