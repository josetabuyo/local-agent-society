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
import re
import unicodedata
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


# ── agent names as dictation hears them ──────────────────────────────────────
#
# Whisper writes names it doesn't know the way they sound: "Wavi" comes out
# "guabi", "uabi", "wabi". Before routing, every word whose Spanish sound
# matches an agent's name is rewritten to the name, so both the model and the
# agent that receives the text read "Wavi". An agent can add spellings the
# sound key misses with `heard_as` in its .las-agent.json.

_DIGRAPHS = [(r"g[uü](?=[aeiou])", "w"), (r"h?u(?=[aeio])", "w"), (r"qu(?=[ei])", "k"), (r"c(?=[ei])", "s"),
             (r"ch", "x"), (r"ll", "y"), (r"c|q", "k"), (r"z", "s"), (r"h", ""), (r"[vw]", "b"), (r"j", "g"), (r"ee", "i")]


def sound_key(word: str) -> str:
    """A rough Spanish-ear phonetic key: guabi, uabi, wabi and Wavi all → "babi"."""
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(ch for ch in w if not unicodedata.combining(ch) or ch == "\u0308")
    w = w.replace("u\u0308", "ü")
    w = re.sub(r"[^a-zñü]", "", w)
    for pat, rep in _DIGRAPHS:
        w = re.sub(pat, rep, w)
    w = w.replace("y", "i")
    return re.sub(r"(.)\1+", r"\1", w)


def name_fixes(configs: dict[str, dict]) -> dict[str, str]:
    """sound key / lowercase alias → canonical agent name. Only one-word names
    of 4+ letters (short keys collide with ordinary words); a key two agents
    share is dropped — ambiguous, so never rewritten."""
    fixes: dict[str, str] = {}
    clash: set[str] = set()
    for name, cfg in configs.items():
        keys = set()
        if re.fullmatch(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü]{4,}", name):
            keys.add(sound_key(name))
        for alias in cfg.get("heard_as") or []:
            if isinstance(alias, str) and alias.strip():
                keys.add(alias.strip().lower())
        for k in keys:
            if k in fixes and fixes[k] != name:
                clash.add(k)
            fixes[k] = name
    return {k: v for k, v in fixes.items() if k not in clash}


def fix_names(text: str, fixes: dict[str, str]) -> str:
    """Rewrite each word (or multi-word heard_as alias) that sounds like an agent's name to that name."""
    for alias, name in sorted(((a, n) for a, n in fixes.items() if " " in a), key=lambda x: -len(x[0])):
        text = re.sub(rf"(?i)\b{re.escape(alias)}\b", name, text)

    def one(m: re.Match) -> str:
        word = m.group(0)
        name = fixes.get(word.lower()) or fixes.get(sound_key(word))
        return name if name and len(word) >= 3 else word   # agents need 4+ letters to get a key at all (name_fixes)
    return re.sub(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü]+", one, text)


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


# ── is the router usable on this machine? ────────────────────────────────────
#
# The general mic is optional: it needs LocalModels' router (ROUTER_URL) and,
# behind it, Ollama with the decision model pulled. A Mac without them gets a
# notice that says what to install, never a mic that records and goes nowhere.

OLLAMA_URL = os.getenv("LAS_OLLAMA_URL", "http://localhost:11434")
ROUTER_MODEL = os.getenv("LAS_ROUTER_MODEL", "d3")   # name prefix in `ollama list`
STATUS_TIMEOUT_S = 1.5


def _get_json(url: str, timeout: float = STATUS_TIMEOUT_S) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def status(*, getter=_get_json) -> dict:
    """{available, router, ollama, model, missing: [what to install]} — fast, never raises."""
    out = {"available": False, "router": False, "ollama": False, "model": None, "missing": [],
           "router_url": ROUTER_URL, "model_wanted": ROUTER_MODEL}
    try:
        out["router"] = (getter(ROUTER_URL.rstrip("/") + "/health") or {}).get("status") == "ok"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    try:
        tags = getter(OLLAMA_URL.rstrip("/") + "/api/tags") or {}
        out["ollama"] = True
        out["model"] = next((m.get("name") for m in tags.get("models") or []
                             if (m.get("name") or "").split(":")[0] == ROUTER_MODEL), None)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    if not out["ollama"]:
        out["missing"].append("ollama")
    elif not out["model"]:
        out["missing"].append(f"model {ROUTER_MODEL}")
    if not out["router"]:
        out["missing"].append("LocalModels router")
    out["available"] = not out["missing"]
    # Pulpo is optional: without it the backend decides by itself.
    out["engine"] = "pulpo" if ROUTE_ENGINE == "pulpo" and pulpo_up() else "local"
    return out


# ── the decision, as a Pulpo flow ────────────────────────────────────────────
#
# The routing pipeline (vocabulary fix → live candidates → d3 → deliver /
# pending) lives as Pulpo's "las-dictation" flow, where it can be seen, edited
# and tested in Pulpo's editor. Pulpo owns the flow; LAS only calls it and
# delivers. It decides, never delivers. The response is this module's own
# shape (route()). When Pulpo is down, slow (HTTP 504) or answers garbage,
# the backend runs route() itself, so 🧭 never depends on Pulpo being up.
# LAS_ROUTE_ENGINE=local skips Pulpo entirely.

PULPO_FLOW_URL = os.getenv("LAS_PULPO_FLOW_URL", "http://localhost:9010/api/flows/las-dictation/trigger/entrada")
ROUTE_ENGINE = os.getenv("LAS_ROUTE_ENGINE", "pulpo")
PULPO_FLOW_TIMEOUT_MS = int(os.getenv("LAS_PULPO_FLOW_TIMEOUT_MS", "15000"))


def _post_json(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def route_via_pulpo(text: str, level: str = "agent", agent: str | None = None, from_agent: str | None = None,
                    *, caller=_post_json) -> dict | None:
    """Pulpo's decision, or None (→ caller falls back to route()). Never raises."""
    if ROUTE_ENGINE != "pulpo":
        return None
    data = {"text": text, "level": level, "from_agent": from_agent or "LocalAgentSociety"}
    if agent:
        data["agent"] = agent
    try:
        out = caller(PULPO_FLOW_URL, {"wait": True, "timeout_ms": PULPO_FLOW_TIMEOUT_MS, "data": data},
                     PULPO_FLOW_TIMEOUT_MS / 1000 + 3)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    res = (out or {}).get("response")
    if not isinstance(res, dict) or res.get("decision") not in ("deliver", "pending") or not isinstance(res.get("ranked"), list):
        return None
    res.setdefault("text", text)
    res["engine"] = "pulpo"
    res["run_id"] = out.get("run_id")
    return res


def pulpo_up(timeout: float = 0.5) -> bool:
    """Is anything listening on the flow's host:port? (Cheap: no Next.js compile.)"""
    import socket
    from urllib.parse import urlparse
    u = urlparse(PULPO_FLOW_URL)
    try:
        with socket.create_connection((u.hostname or "localhost", u.port or 80), timeout=timeout):
            return True
    except OSError:
        return False


# ── warm-up: load d3 while the human is still talking ────────────────────────
#
# Cold, d3 takes 6-16 s to answer; warm, under a second of model time. The
# widget asks for a warm-up the moment 🧭 starts recording, so by the time the
# dictation is transcribed the model is resident. Straight to Ollama (the
# router's own call uses Ollama's 5-minute default keep_alive); d3 only takes
# /v1/systemone, so the warm-up is a one-question decision (LocalModels' recipe).
WARM_KEEP_ALIVE = os.getenv("LAS_ROUTER_KEEP_ALIVE", "10m")


def warm(model: str | None = None, *, timeout: float = 30.0, caller=None) -> bool:
    """Load the decision model into memory. Blocking; returns whether it answered."""
    model = model or status().get("model")
    if not model:
        return False
    body = {"model": model, "keep_alive": WARM_KEEP_ALIVE, "state": "warm",
            "questions": {"w": {"type": "noul", "instructions": "ok"}}}
    try:
        if caller:
            caller(body)
        else:
            req = urllib.request.Request(OLLAMA_URL.rstrip("/") + "/v1/systemone", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read()
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


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
