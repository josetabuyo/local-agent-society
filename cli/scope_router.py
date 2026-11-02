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


def agent_candidates(configs: dict[str, dict], rung: str = "short") -> dict[str, str]:
    """Agent name → scope text, for every agent whose config has one.

    rung="short" (the first pass) prefers short_description: d3's time is
    ~4 ms per prompt token, and LocalModels measured 24 agents at 537 tokens /
    ~2 s on short vs 900 / ~3.6 s on long, same accuracy (12/12). rung="long"
    (the second pass, over a pending's top few) prefers long_description."""
    order = ("short_description", "long_description") if rung == "short" else ("long_description", "short_description")
    out = {}
    for name, cfg in configs.items():
        scope = next((cfg[k].strip() for k in order if isinstance(cfg.get(k), str) and cfg[k].strip()), "")
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
# The general mic is optional: it needs LocalModels (its router, Ollama and
# the decision model). Which model, which tag per platform, whether it is
# loaded — all of that is LocalModels' business, asked through the router's
# own GET /status; LAS never names a model. A Mac without it gets a notice
# that says what's missing, never a mic that records and goes nowhere.

STATUS_TIMEOUT_S = 1.5


def _get_json(url: str, timeout: float = STATUS_TIMEOUT_S) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def status(*, getter=_get_json) -> dict:
    """{available, router, ollama, model, missing: [what to install], engine} — fast, never raises."""
    out = {"available": False, "router": False, "ollama": False, "model": None, "missing": [], "router_url": ROUTER_URL}
    try:
        st = getter(ROUTER_URL.rstrip("/") + "/status") or {}
        out["router"] = bool((st.get("router") or {}).get("up"))
        out["ollama"] = bool((st.get("ollama") or {}).get("up"))
        model = st.get("model") or {}
        out["model"] = model.get("name") if model.get("installed") else None
        out["warm"] = bool((st.get("warm") or {}).get("loaded"))
        if not out["ollama"]:
            out["missing"].append("ollama")
        elif not out["model"]:
            out["missing"].append(f"model {model.get('name') or 'd3'}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError):
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


# ── warm-up: load the model while the human is still talking ─────────────────
#
# Cold, the decision model takes 6-16 s; warm, a couple. The widget asks for a
# warm-up the moment 🧭 starts recording, so by the time the dictation is
# transcribed the model is resident. The router's POST /v1/warm picks the
# model and how long it stays loaded (LocalModels owns both).


def warm(*, timeout: float = 30.0, caller=None) -> bool:
    """Ask the router to load its decision model. Blocking; returns whether it did."""
    try:
        if caller:
            out = caller({})
        else:
            req = urllib.request.Request(ROUTER_URL.rstrip("/") + "/v1/warm", data=b"{}",
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read())
        return bool((out or {}).get("ok"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def route(text: str, criteria: dict[str, str], level: str = "agent", *, detail: dict[str, str] | None = None,
          caller=call_router) -> dict:
    """Ask the model and decide. Never raises: a router failure is `pending`.

    `detail` (name → longer scope text) enables a second pass: a pending pick
    is asked again over just its top few, with their longer descriptions —
    3 options cost under a second."""
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
    first = decide(response)
    if first["decision"] == "deliver" or not detail or (first["router"] or {}).get("fallback_used"):
        return first
    top = {r["name"]: detail.get(r["name"]) or criteria[r["name"]] for r in first["ranked"] if r["name"] in criteria}
    if len(top) < 2 or top == {n: criteria[n] for n in top}:
        return first   # nothing new to tell the model
    try:
        second = decide(caller(build_request(text, top, level)))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return first
    second["passes"] = 2
    if second["decision"] != "deliver":
        second["ranked"] = second["ranked"] or first["ranked"]
    return second
