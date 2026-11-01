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


class FakeChat:
    """Returns the scripted messages in order; records which tools it was shown."""
    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen_tools = []
        self.seen_system = []

    def __call__(self, messages, tools):
        self.seen_tools.append([t["function"]["name"] for t in tools])
        self.seen_system.append(messages[0]["content"])
        return self.replies.pop(0)


def _agent(chat, selector=None, calls=None, skills=(), confirm=lambda p, o: True):
    return la.LocalAgent(name="Pulpo", agent_dir="/tmp", tools=_tools(calls if calls is not None else []),
                         skills=list(skills), chat=chat, selector=selector, confirm=confirm)


def _picks(choice, p=0.9, second=0.05):
    def selector(text, options, context=""):
        assert choice in options
        other = next(k for k in options if k != choice)
        return la.scope_router.decide({"answers": {"agent": {"probabilities": {choice: p, other: second}}}})
    return selector


def test_confident_pick_narrows_the_tools_to_that_one():
    calls = []
    chat = FakeChat({"tool_calls": [{"function": {"name": "list_agents", "arguments": {}}}]},
                    {"content": "Está Pulpo con claude y local."})
    answer = _agent(chat, _picks("list_agents"), calls).handle(la.Turn("¿quién está conectado?"))
    assert answer == "Está Pulpo con claude y local."
    assert chat.seen_tools[0] == ["list_agents"]
    assert calls == [("list_agents",)]


def test_chat_pick_offers_no_tools():
    chat = FakeChat({"content": "hola"})
    _agent(chat, _picks("chat")).handle(la.Turn("hola"))
    assert chat.seen_tools == [[]]


def test_weak_pick_falls_back_to_every_tool():
    chat = FakeChat({"content": "?"})
    _agent(chat, _picks("run_shell", p=0.45, second=0.40)).handle(la.Turn("algo raro"))
    assert chat.seen_tools == [["list_agents", "run_shell"]]


def test_dead_selector_falls_back_to_every_tool():
    def boom(body):
        raise OSError("connection refused")
    chat = FakeChat({"content": "ok"})
    agent = _agent(chat, lambda t, o, c="": la.select(t, o, c, caller=boom))
    agent.handle(la.Turn("x"))
    assert chat.seen_tools == [["list_agents", "run_shell"]]


def test_chosen_skill_enters_the_system_prompt_only_when_picked():
    sk = la.Skill("deploy", "deploy the web app", "Run npx vercel --prod from web/.")
    chat = FakeChat({"content": "a"}, {"content": "b"})
    agent = _agent(chat, _picks("skill:deploy"), skills=[sk])
    agent.handle(la.Turn("deployá"))
    assert "npx vercel --prod" in chat.seen_system[0]
    agent.selector = _picks("chat")
    agent.handle(la.Turn("gracias"))
    assert "npx vercel --prod" not in chat.seen_system[1]


def test_declined_confirmation_does_not_run_the_tool():
    calls = []
    chat = FakeChat({"tool_calls": [{"function": {"name": "run_shell", "arguments": {"command": "rm -rf x"}}}]},
                    {"content": "no lo corrí"})
    _agent(chat, None, calls, confirm=lambda p, o: False).handle(la.Turn("borrá x"))
    assert calls == []


def test_tool_rounds_are_capped():
    loop = {"tool_calls": [{"function": {"name": "list_agents", "arguments": "{}"}}]}
    chat = FakeChat(*[loop] * (la.MAX_TOOL_ROUNDS + 1))
    answer = _agent(chat).handle(la.Turn("x"))
    assert "too many tool calls" in answer


def test_history_is_bounded_and_tool_chatter_dropped():
    chat = FakeChat(*[{"content": str(i)} for i in range(20)])
    agent = _agent(chat)
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
    agent = _agent(FakeChat({"content": "¡hola!"}))
    rt = la.LocalRuntime(agent, bridge_argv=None, stdin=io.StringIO("hola\n/exit\n"), out=out)
    assert rt.run() == 0
    assert "Pulpo › ¡hola!" in out.getvalue()
    assert sent == []   # terminal turns are only printed


def test_runtime_replies_to_the_sending_agent(monkeypatch):
    sent = []
    monkeypatch.setattr(la, "_sh", lambda argv, **k: sent.append(argv) or "")
    agent = _agent(FakeChat({"content": "listo"}))
    rt = la.LocalRuntime(agent, bridge_argv=None, las="las", out=io.StringIO())
    turn = la.envelope_to_turn({"from": "Wavi", "source": "agent", "text": "hacé algo"}, "Pulpo")
    rt.deliver(turn, agent.handle(turn))
    assert sent == [["las", "agent", "send", "--to", "Wavi", "--from", "Pulpo", la.AUTO_REPLY_MARK + "listo"]]


def test_select_builds_a_systemone_choice():
    seen = {}

    def caller(body):
        seen.update(body)
        return {"answers": {"agent": {"probabilities": {"chat": 0.9, "x": 0.1}}}}
    res = la.select("hola", {"chat": "talk", "x": "do x"}, "User: antes", caller=caller)
    assert res["decision"] == "deliver" and res["choice"] == "chat"
    assert seen["questions"]["agent"]["type"] == "choice"
    assert json.dumps(seen["questions"]["agent"]["criteria"]) == json.dumps({"chat": "talk", "x": "do x"})
    assert "User: hola" in seen["state"]


def test_sessions_listing_is_flattened_per_agent():
    raw = ('LocalModels\n  claude-31453-820a3a          claude      "Guardados IG"  *default\n'
           'Pulpo\n  claude-75682-22ce71          claude      "Nodo Jev"  *default\n  local-1  local\n')
    assert la.flatten_sessions(raw).splitlines() == [
        'agent LocalModels: one claude terminal open — working on "Guardados IG"',
        'agent Pulpo: one claude terminal open — working on "Nodo Jev"',
        'agent Pulpo: one local terminal open',
    ]


def test_confident_pick_keeps_a_strong_runner_up():
    def selector(text, options, context=""):
        return la.scope_router.decide({"answers": {"agent": {"probabilities": {"run_shell": 0.59, "list_agents": 0.31, "chat": 0.05}}}})
    chat = FakeChat({"content": "ok"})
    _agent(chat, selector).handle(la.Turn("x"))
    assert chat.seen_tools == [["list_agents", "run_shell"]]


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
    chat = FakeChat({"tool_calls": [{"function": {"name": "run_shell", "arguments": {"command": "ls"}}}]},
                    {"content": "ok"})
    agent = _agent(chat, confirm=lambda p, o: seen.append(o) or False)
    agent.handle(la.Turn("ls", "agent", "Wavi"))
    assert seen == ["agent"]


def test_automatic_replies_are_never_answered():
    assert la.envelope_to_turn({"from": "Wavi", "source": "agent", "text": la.AUTO_REPLY_MARK + "listo"}, "Pulpo") is None


def test_replies_to_one_sender_are_capped_per_minute():
    rt = la.LocalRuntime(_agent(FakeChat()), bridge_argv=None, out=io.StringIO())
    assert [rt.may_reply("Wavi", now=t) for t in range(la.REPLIES_PER_MINUTE + 1)] == [True] * la.REPLIES_PER_MINUTE + [False]
    assert rt.may_reply("Teli", now=5) is True
    assert rt.may_reply("Wavi", now=100) is True


def test_spoken_answer_and_title_are_never_cut(monkeypatch):
    sent = []
    monkeypatch.setattr(la, "_sh", lambda argv, **k: sent.append(argv) or "")
    long = "x" * 900
    agent = _agent(FakeChat({"content": "Un título bastante más largo que treinta y cuatro caracteres"}))
    rt = la.LocalRuntime(agent, bridge_argv=None, out=io.StringIO())
    rt.deliver(la.Turn("hola", "human"), long)
    assert sent[-1][2] == long
    rt.last_topic = "algo"
    rt.answer_title_request({"text": "las agent title ... --session local-1-abc"})
    assert sent[-1][3] == "Un título bastante más largo que treinta y cuatro caracteres"
    assert sent[-1][-2:] == ["--session", "local-1-abc"]


def test_title_falls_back_to_the_whole_topic(monkeypatch):
    def down(messages, tools):
        raise OSError("ollama down")
    rt = la.LocalRuntime(_agent(down), bridge_argv=None, out=io.StringIO())
    rt.last_topic = "una consulta larga sobre los puertos de la base de datos local"
    assert rt.make_title() == rt.last_topic
