"""Scope router: cli/scope_router.py's decision rules and the backend's
POST /route + /route/choose. The model (LocalModels' /v1/systemone) is
never called — every test hands in a canned response."""
import json
import sys
import threading as _threading
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from cli import scope_router as sr


def response(probs, fallback=False, noul=0.6):
    top = max(probs, key=probs.get)
    return {"answers": {"agent": {"type": "choice", "choice": top, "confidence": probs[top], "probabilities": probs},
                        "confident": {"type": "noul", "noul": noul}},
            "x_router": {"resolved": "ollama/d3:4b-nvfp4", "local": True, "fallback_used": fallback}}


# ── pure decision rules ───────────────────────────────────────────────────────

def test_confident_pick_is_delivered():
    d = sr.decide(response({"LocalAgentSociety": 0.72, "bau": 0.23, "AppBlanca": 0.02, "Wavi": 0.01}))
    assert d["decision"] == "deliver"
    assert d["choice"] == "LocalAgentSociety"
    assert [r["name"] for r in d["ranked"]] == ["LocalAgentSociety", "bau", "AppBlanca"]  # top 3 only


def test_low_noul_does_not_block_a_clear_pick():
    """The `confident` noul runs 0.53-0.80 on correct picks — never cut on it."""
    assert sr.decide(response({"A": 0.8, "B": 0.1}, noul=0.4))["decision"] == "deliver"


def test_weak_top_is_pending():
    d = sr.decide(response({"A": 0.45, "B": 0.1, "C": 0.1}))
    assert d["decision"] == "pending" and "top pick" in d["reason"]


def test_close_runner_up_is_pending():
    d = sr.decide(response({"A": 0.55, "B": 0.4}))
    assert d["decision"] == "pending" and "margin" in d["reason"]
    assert d["choice"] == "A"  # still suggested, as the first chip


def test_cloud_fallback_is_pending():
    d = sr.decide(response({"A": 0.9, "B": 0.05}, fallback=True))
    assert d["decision"] == "pending" and "cloud" in d["reason"]


def test_router_down_is_pending_never_raises():
    def down(_body):
        raise urllib.error.URLError("connection refused")
    d = sr.route("hola", {"A": "x", "B": "y"}, caller=down)
    assert d["decision"] == "pending" and "unavailable" in d["reason"]


def test_single_candidate_skips_the_model():
    d = sr.route("hola", {"Only": "x"}, caller=lambda b: pytest.fail("model called"))
    assert d["decision"] == "deliver" and d["choice"] == "Only"


def test_no_candidates_is_pending():
    assert sr.route("hola", {}, caller=lambda b: pytest.fail("model called"))["decision"] == "pending"


def test_candidates_use_the_scope_ladder():
    crit = sr.agent_candidates({"A": {"long_description": "long", "short_description": "short"},
                                "B": {"short_description": "short"}, "C": {"name": "C"}})
    assert crit == {"A": "short", "B": "short"}  # short first (prompt length is d3's cost); C has no scope
    assert sr.agent_candidates({"A": {"long_description": "long", "short_description": "short"},
                                "B": {"short_description": "short"}}, rung="long") == {"A": "long", "B": "short"}


def test_session_candidates_skip_untitled_and_shells():
    crit = sr.session_candidates([{"sid": "s1", "title": "Router de mic"}, {"sid": "s2", "title": ""},
                                  {"sid": "s3", "title": "make", "intelligent": False}])
    assert crit == {"s1": "Router de mic"}


def test_request_shape_matches_systemone():
    body = sr.build_request("hola", {"A": "x"})
    assert body["state"] == "hola"
    assert body["questions"]["agent"] == {"type": "choice", "instructions": sr.INSTRUCTIONS["agent"], "criteria": {"A": "x"}}
    assert body["questions"]["confident"]["type"] == "noul"


# ── backend endpoints ─────────────────────────────────────────────────────────

class _NoStartThread(_threading.Thread):
    def start(self):
        pass


@pytest.fixture
def backend(tmp_path, monkeypatch):
    if "backend.main" in sys.modules:
        del sys.modules["backend.main"]
    monkeypatch.setattr(_threading, "Thread", _NoStartThread)
    import backend.main as main
    monkeypatch.undo()
    for attr in ("REGISTRY_FILE", "SESSIONS_FILE", "INACTIVE_FILE", "WAKE_ENABLED_FILE"):
        monkeypatch.setattr(main, attr, tmp_path / f"{attr.lower()}.json")
    monkeypatch.setattr(main, "ROUTE_LOG_FILE", tmp_path / "route_log.jsonl")
    monkeypatch.setattr(sr, "ROUTE_ENGINE", "local")   # never reach a real Pulpo from a test
    published = []
    monkeypatch.setattr(main, "_vortexia_publish",
                        lambda topic, envelope, retain=False: (published.append((topic, envelope)), True)[1])
    main._published = published
    registry = {}
    for name, desc in {"LocalAgentSociety": "widget, mic, ports", "Wavi": "WhatsApp automation", "Mute": None}.items():
        folder = tmp_path / name
        folder.mkdir()
        (folder / ".las-agent.json").write_text(json.dumps({"name": name, **({"long_description": desc} if desc else {})}))
        registry[name] = {"name": name, "path": str(folder), "voice": "Paulina"}
    main.save_json(main.REGISTRY_FILE, registry)
    return main


def test_route_endpoint_delivers_as_mic(backend, monkeypatch):
    seen = []
    monkeypatch.setattr(sr, "route", lambda text, crit, level="agent", **k: (seen.append(crit), sr.decide(response({"Wavi": 0.9, "LocalAgentSociety": 0.05})))[1])
    res = TestClient(backend.app).post("/route", json={"text": "mandale un whatsapp a Diego", "deliver": True}).json()
    assert res["decision"] == "deliver" and res["choice"] == "Wavi" and res["delivered"]["ok"]
    assert seen[0] == {"LocalAgentSociety": "widget, mic, ports", "Wavi": "WhatsApp automation"}  # Mute has no scope
    topic, env = backend._published[-1]
    assert env["to"] == "Wavi" and env["from"] == "Wavi" and env["source"] == "human"  # reads as mic in Wavi's widget
    log = [json.loads(l) for l in backend.ROUTE_LOG_FILE.read_text().splitlines()]
    assert log[-1]["choice"] == "Wavi" and log[-1]["delivered"] is True


def test_route_endpoint_pending_does_not_send(backend, monkeypatch):
    monkeypatch.setattr(sr, "route", lambda text, crit, level="agent", **k: sr.decide(response({"Wavi": 0.5, "LocalAgentSociety": 0.45})))
    res = TestClient(backend.app).post("/route", json={"text": "algo ambiguo", "deliver": True}).json()
    assert res["decision"] == "pending" and "delivered" not in res
    assert backend._published == []


def test_route_choose_delivers_and_logs_correction(backend):
    res = TestClient(backend.app).post("/route/choose", json={"text": "algo", "choice": "LocalAgentSociety", "suggested": "Wavi"})
    assert res.status_code == 200
    assert backend._published[-1][1]["to"] == "LocalAgentSociety"
    log = json.loads(backend.ROUTE_LOG_FILE.read_text().splitlines()[-1])
    assert log["correction"] is True and log["suggested"] == "Wavi"


def test_route_choose_unknown_agent_is_404(backend):
    assert TestClient(backend.app).post("/route/choose", json={"text": "x", "choice": "Nadie"}).status_code == 404


def test_route_bad_level_is_422(backend):
    assert TestClient(backend.app).post("/route", json={"text": "x", "level": "planet"}).status_code == 422


# ── misheard agent names ──────────────────────────────────────────────────────

def test_whisper_spellings_of_wavi_become_wavi():
    fixes = sr.name_fixes({"Wavi": {}, "System": {}, "Pulpo": {}})
    for heard in ("guabi", "Guabi", "uabi", "wabi", "huabi", "wavi"):
        assert sr.fix_names(f"mandar un mensaje con {heard}", fixes) == "mandar un mensaje con Wavi"


def test_ordinary_words_are_left_alone():
    fixes = sr.name_fixes({"System": {}, "Forti": {}, "Teli": {}})
    text = "el sistema anda lento, algo fuerte en la tele"
    assert sr.fix_names(text, fixes) == text


def test_heard_as_aliases_and_ambiguous_keys():
    fixes = sr.name_fixes({"RuGIAR": {"heard_as": ["robot universidad", "rugiar"]}, "Baby": {}, "Wavi": {}})
    assert sr.fix_names("hablale a robot universidad", fixes) == "hablale a RuGIAR"
    assert "babi" not in fixes   # Baby and Wavi share the key: ambiguous, never rewritten
    assert sr.fix_names("con guabi", fixes) == "con guabi"


def test_route_endpoint_fixes_names_before_routing_and_delivery(backend, monkeypatch):
    seen = []
    monkeypatch.setattr(sr, "route", lambda text, crit, level="agent", **k: (seen.append(text), sr.decide(response({"Wavi": 0.9, "LocalAgentSociety": 0.05})))[1])
    res = TestClient(backend.app).post("/route", json={"text": "mandale algo con guabi", "deliver": True}).json()
    assert seen == ["mandale algo con Wavi"] and res["text"] == "mandale algo con Wavi"
    assert backend._published[-1][1]["text"] == "mandale algo con Wavi"
    log = json.loads(backend.ROUTE_LOG_FILE.read_text().splitlines()[-1])
    assert log["heard"] == "mandale algo con guabi"


# ── dictation vocabulary (cli/vocabulary.py, POST /dictation/fix) ─────────────

from cli import vocabulary as vocab


def test_vocabulary_fixes_spanglish_dev_terms(tmp_path):
    fixes = vocab.build_fixes({"Wavi": {}}, user_file=tmp_path / "none.txt")
    assert vocab.fix_text("hacé un commit en JIT y abrí el pul request en guit hub", fixes) == \
        "hacé un commit en git y abrí el pull request en GitHub"
    assert vocab.fix_text("el bakend manda el yeison", fixes) == "el backend manda el JSON"
    assert vocab.fix_text("con guabi", fixes) == "con Wavi"


def test_vocabulary_leaves_plain_spanish_alone(tmp_path):
    fixes = vocab.build_fixes({"System": {}, "Forti": {}, "Teli": {}}, user_file=tmp_path / "none.txt")
    text = "la casa, la fuente del sistema, el cliente pagó, la cola del banco, quiero comer pasta"
    assert vocab.fix_text(text, fixes) == text


def test_user_vocabulary_file(tmp_path):
    f = tmp_path / "vocabulary.txt"
    vocab.add_entry("Supabase", f)
    vocab.add_entry("supa beis => Supabase   # how it comes out", f)
    fixes = vocab.build_fixes({}, user_file=f)
    assert vocab.fix_text("conectá supa beis", fixes) == "conectá Supabase"
    assert vocab.fix_text("conectá supabase", fixes) == "conectá Supabase"   # a plain term: matched by sound


def test_dictation_fix_endpoint_uses_the_live_agent_names(backend, monkeypatch, tmp_path):
    monkeypatch.setattr(vocab, "USER_FILE", tmp_path / "none.txt")
    c = TestClient(backend.app)
    assert c.post("/dictation/fix", json={"text": "decile a guabi"}).json() == {"text": "decile a Wavi", "changed": True}
    assert c.post("/dictation/fix", json={"text": "hola"}).json() == {"text": "hola", "changed": False}


# ── /route/status: is the general mic usable on this Mac? ────────────────────

def _getter(router_ok=True, ollama=True, models=("d3:4b-nvfp4",)):
    def get(url, timeout=None):
        if url.endswith("/health"):
            if not router_ok:
                raise urllib.error.URLError("refused")
            return {"status": "ok"}
        if not ollama:
            raise urllib.error.URLError("refused")
        return {"models": [{"name": m} for m in models]}
    return get


def test_status_available_when_router_ollama_and_model_are_there():
    st = sr.status(getter=_getter())
    assert st["available"] and st["missing"] == [] and st["model"] == "d3:4b-nvfp4"


def test_status_names_each_missing_piece():
    assert sr.status(getter=_getter(ollama=False))["missing"] == ["ollama"]
    assert sr.status(getter=_getter(models=("qwen3.5:4b", "d3x:1b")))["missing"] == ["model d3"]
    st = sr.status(getter=_getter(router_ok=False, ollama=False))
    assert not st["available"] and st["missing"] == ["ollama", "LocalModels router"]


def test_warm_sends_a_one_question_decision_with_keep_alive():
    sent = []
    assert sr.warm("d3:4b-nvfp4", caller=sent.append)
    assert sent[0]["model"] == "d3:4b-nvfp4" and sent[0]["keep_alive"] == sr.WARM_KEEP_ALIVE
    assert sent[0]["questions"]["w"]["type"] == "noul"


def test_warm_without_model_or_with_a_failing_call_is_false_not_an_error(monkeypatch):
    monkeypatch.setattr(sr, "status", lambda: {"model": None})
    assert sr.warm() is False
    def boom(body):
        raise urllib.error.URLError("refused")
    assert sr.warm("d3:4b-nvfp4", caller=boom) is False


# ── Pulpo's "las-dictation" flow decides; the backend falls back to itself ────

PULPO_OK = {"run_id": "wrun_1", "response": {"decision": "deliver", "choice": "Wavi", "confidence": 0.72, "margin": 0.57,
            "ranked": [{"name": "Wavi", "p": 0.72}, {"name": "Monkey", "p": 0.15}], "reason": None,
            "text": "mandale un whatsapp a Wavi", "router": {"local": True}}}


def test_route_via_pulpo_sends_the_flow_contract_and_returns_its_decision(monkeypatch):
    monkeypatch.setattr(sr, "ROUTE_ENGINE", "pulpo")
    calls = []
    res = sr.route_via_pulpo("mandale un guasap a guabi", "session", "Pulpo", "Wavi",
                             caller=lambda url, body, timeout: (calls.append((url, body, timeout)), PULPO_OK)[1])
    url, body, timeout = calls[0]
    assert url == sr.PULPO_FLOW_URL and body["wait"] is True and body["timeout_ms"] == sr.PULPO_FLOW_TIMEOUT_MS
    assert body["data"] == {"text": "mandale un guasap a guabi", "level": "session", "from_agent": "Wavi", "agent": "Pulpo"}
    assert timeout > sr.PULPO_FLOW_TIMEOUT_MS / 1000   # the flow's own 504 comes back before the socket gives up
    assert res["choice"] == "Wavi" and res["engine"] == "pulpo" and res["run_id"] == "wrun_1"


@pytest.mark.parametrize("outcome", [urllib.error.URLError("refused"), TimeoutError(), {"run_id": "x", "error": "timeout"},
                                     {"response": {"decision": "maybe"}}, None])
def test_route_via_pulpo_is_none_when_pulpo_is_down_slow_or_odd(monkeypatch, outcome):
    monkeypatch.setattr(sr, "ROUTE_ENGINE", "pulpo")
    def caller(url, body, timeout):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    assert sr.route_via_pulpo("hola", caller=caller) is None


def test_route_via_pulpo_off_when_engine_is_local(monkeypatch):
    monkeypatch.setattr(sr, "ROUTE_ENGINE", "local")
    assert sr.route_via_pulpo("hola", caller=lambda *a: PULPO_OK) is None


def test_route_endpoint_uses_pulpo_then_falls_back(backend, monkeypatch):
    monkeypatch.setattr(sr, "route_via_pulpo", lambda *a, **k: dict(PULPO_OK["response"], engine="pulpo", run_id="wrun_1"))
    monkeypatch.setattr(sr, "route", lambda *a, **k: pytest.fail("local pipeline must not run when Pulpo decided"))
    res = TestClient(backend.app).post("/route", json={"text": "mandale un guasap a guabi"}).json()
    assert res["engine"] == "pulpo" and res["choice"] == "Wavi" and res["text"] == "mandale un whatsapp a Wavi"
    log = [json.loads(l) for l in backend.ROUTE_LOG_FILE.read_text().splitlines()]
    assert log[-1]["engine"] == "pulpo" and log[-1]["run_id"] == "wrun_1"

    monkeypatch.setattr(sr, "route_via_pulpo", lambda *a, **k: None)
    monkeypatch.setattr(sr, "route", lambda text, crit, level="agent", **k: sr.decide(response({"Wavi": 0.9, "LocalAgentSociety": 0.05})))
    res = TestClient(backend.app).post("/route", json={"text": "mandale un whatsapp"}).json()
    assert res["engine"] == "local" and res["choice"] == "Wavi"


def test_a_pending_first_pass_is_asked_again_over_its_top_few_with_long_descriptions():
    crit = {"Wavi": "WhatsApp", "Teli": "Telegram", "Pulpo": "Bots", "System": "IT"}
    detail = {"Wavi": "WhatsApp automation for the owner's chats", "Teli": "Telegram CLI", "Pulpo": "Flows for Telegram bots",
              "System": "Mac IT"}
    asked = []
    def caller(body):
        c = body["questions"]["agent"]["criteria"]
        asked.append(c)
        if len(asked) == 1:
            return response({"Wavi": 0.4, "Teli": 0.35, "Pulpo": 0.2, "System": 0.05})
        return response({"Wavi": 0.85, "Teli": 0.1, "Pulpo": 0.05})
    res = sr.route("mandale un mensaje", crit, detail=detail, caller=caller)
    assert asked[1] == {n: detail[n] for n in ("Wavi", "Teli", "Pulpo")}   # only the top 3, long text
    assert res["decision"] == "deliver" and res["choice"] == "Wavi" and res["passes"] == 2


def test_no_second_pass_when_the_first_delivers_or_there_is_nothing_longer():
    calls = []
    caller = lambda body: (calls.append(1), response({"Wavi": 0.4, "Teli": 0.35}))[1]
    sr.route("x", {"Wavi": "a", "Teli": "b"}, detail={"Wavi": "a", "Teli": "b"}, caller=caller)
    assert len(calls) == 1
    calls.clear()
    sr.route("x", {"Wavi": "a", "Teli": "b"}, detail={"Wavi": "long a"},
             caller=lambda body: (calls.append(1), response({"Wavi": 0.9, "Teli": 0.05}))[1])
    assert len(calls) == 1
