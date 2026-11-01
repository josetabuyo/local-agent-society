"""Scope router: pick which agent (or which of an agent's sessions) a free
text belongs to, using LocalModels' decision endpoint (POST /v1/systemone).

The candidates are the society's own scope ladder (docs/adr/0001): an
agent's long_description, else its short_description; a session's title.
Agents without either can't be chosen — the ladder IS the routing data.

Only the backend calls the model (one resident local model on a 16 GB Mac);
every client — the widget's general mic, the panel, the phone, `las route` —
goes through the backend's POST /route.

The decision is made on the top probability and its margin over the
runner-up, not on the `confident` noul: LocalModels measured the noul at
0.53-0.80 on correct picks, too low to cut on. A cloud fallback, a router
that's down or slow, or a weak pick never drops the text: it comes back as
`pending` with the best few candidates, for a human to choose.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ROUTER_URL = os.getenv("LAS_ROUTER_URL", "http://localhost:9002")
# Warm d3 answers in ~3.6 s; a cold load takes 8-20 s and comes back pending, never lost.
ROUTER_TIMEOUT_S = float(os.getenv("LAS_ROUTER_TIMEOUT_S", "12"))
MIN_TOP = 0.5      # deliver only if the pick has at least this probability…
MIN_MARGIN = 0.25  # …and beats the runner-up by at least this much
TOP_N = 3          # chips shown when pending

INSTRUCTIONS = {
    "agent": "Which agent should handle this spoken request",
    "session": "Which of this agent's terminal sessions should handle this request",
}


def agent_candidates(configs: dict[str, dict]) -> dict[str, str]:
    """Agent name → scope text, for every agent whose config has one."""
    out = {}
    for name, cfg in configs.items():
        scope = (cfg.get("long_description") or cfg.get("short_description") or "").strip()
        if scope:
            out[name] = scope
    return out


def session_candidates(sessions: list[dict]) -> dict[str, str]:
    """Session id → title, for every titled session that can take prose."""
    return {s["sid"]: s["title"].strip() for s in sessions
            if (s.get("title") or "").strip() and s.get("intelligent", True)}


def build_request(text: str, criteria: dict[str, str], level: str = "agent") -> dict:
    return {"state": text, "questions": {
        "agent": {"type": "choice", "instructions": INSTRUCTIONS.get(level, INSTRUCTIONS["agent"]), "criteria": criteria},
        "confident": {"type": "noul", "instructions": "The request clearly belongs to one candidate"}}}


def call_router(body: dict, url: str = ROUTER_URL, timeout: float = ROUTER_TIMEOUT_S) -> dict:
    req = urllib.request.Request(url.rstrip("/") + "/v1/systemone", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def decide(response: dict, *, min_top: float = MIN_TOP, min_margin: float = MIN_MARGIN, top_n: int = TOP_N) -> dict:
    """Turn a /v1/systemone response into deliver / pending."""
    answer = (response.get("answers") or {}).get("agent") or {}
    probs = answer.get("probabilities") or {}
    if not probs and answer.get("choice"):
        probs = {answer["choice"]: float(answer.get("confidence") or 0)}
    ranked = sorted(({"name": k, "p": round(float(v), 4)} for k, v in probs.items()), key=lambda r: -r["p"])
    top = ranked[0]["p"] if ranked else 0.0
    second = ranked[1]["p"] if len(ranked) > 1 else 0.0
    margin = round(top - second, 4)
    x_router = response.get("x_router") or {}
    noul = ((response.get("answers") or {}).get("confident") or {}).get("noul")

    reason = None
    if not ranked:
        reason = "router returned no candidates"
    elif x_router.get("fallback_used"):
        reason = "router fell back to the cloud model"
    elif top < min_top:
        reason = f"top pick {top:.2f} < {min_top}"
    elif margin < min_margin:
        reason = f"margin {margin:.2f} over the runner-up < {min_margin}"

    return {"decision": "pending" if reason else "deliver",
            "choice": ranked[0]["name"] if ranked else None,
            "confidence": top, "margin": margin, "confident": noul,
            "ranked": ranked[:top_n], "reason": reason,
            "router": {k: x_router.get(k) for k in ("resolved", "local", "fallback_used") if k in x_router}}


def route(text: str, criteria: dict[str, str], level: str = "agent", *, caller=call_router) -> dict:
    """Ask the model and decide. Never raises: a router failure is `pending`."""
    if not criteria:
        return {"decision": "pending", "choice": None, "confidence": 0.0, "margin": 0.0, "confident": None,
                "ranked": [], "reason": "no candidates with a scope description", "router": {}}
    if len(criteria) == 1:
        only = next(iter(criteria))
        return {"decision": "deliver", "choice": only, "confidence": 1.0, "margin": 1.0, "confident": None,
                "ranked": [{"name": only, "p": 1.0}], "reason": None, "router": {"resolved": "single-candidate"}}
    try:
        response = caller(build_request(text, criteria, level))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"decision": "pending", "choice": None, "confidence": 0.0, "margin": 0.0, "confident": None,
                "ranked": [], "reason": f"router unavailable: {exc}", "router": {}}
    return decide(response)
