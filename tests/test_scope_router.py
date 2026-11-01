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
    assert crit == {"A": "long", "B": "short"}  # C has no scope → can't be chosen


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
    monkeypatch.setattr(sr, "route", lambda text, crit, level="agent": (seen.append(crit), sr.decide(response({"Wavi": 0.9, "LocalAgentSociety": 0.05})))[1])
    res = TestClient(backend.app).post("/route", json={"text": "mandale un whatsapp a Diego", "deliver": True}).json()
    assert res["decision"] == "deliver" and res["choice"] == "Wavi" and res["delivered"]["ok"]
    assert seen[0] == {"LocalAgentSociety": "widget, mic, ports", "Wavi": "WhatsApp automation"}  # Mute has no scope
    topic, env = backend._published[-1]
    assert env["to"] == "Wavi" and env["from"] == "Wavi" and env["source"] == "human"  # reads as mic in Wavi's widget
    log = [json.loads(l) for l in backend.ROUTE_LOG_FILE.read_text().splitlines()]
    assert log[-1]["choice"] == "Wavi" and log[-1]["delivered"] is True


def test_route_endpoint_pending_does_not_send(backend, monkeypatch):
    monkeypatch.setattr(sr, "route", lambda text, crit, level="agent": sr.decide(response({"Wavi": 0.5, "LocalAgentSociety": 0.45})))
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
