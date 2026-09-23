"""
Local Agent Society — Backend
Port: 8700
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional
import json
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
import random
import socket
from pathlib import Path
from datetime import datetime

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))  # backend/ — for `import vortexia_client` regardless of how main.py itself was imported
import vortexia_client as vx
from logging_config import logger

app = FastAPI(title="Local Agent Society", version="1.0.0")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

REGISTRY_FILE = DATA_DIR / "registry.json"
QUEUE_FILE    = DATA_DIR / "queue.json"
PORTS_FILE       = DATA_DIR / "ports.json"
ATTRIBUTION_FILE = DATA_DIR / "attribution.json"
MUTED_FILE    = DATA_DIR / "muted.json"
INACTIVE_FILE      = DATA_DIR / "inactive.json"
WAKE_ENABLED_FILE  = DATA_DIR / "wake_enabled.json"

NICE_VOICES = [
    {"name": "Samantha",               "lang": "en-US", "flag": "🇺🇸"},
    {"name": "Daniel",                 "lang": "en-GB", "flag": "🇬🇧"},
    {"name": "Moira",                  "lang": "en-IE", "flag": "🇮🇪"},
    {"name": "Karen",                  "lang": "en-AU", "flag": "🇦🇺"},
    {"name": "Tessa",                  "lang": "en-ZA", "flag": "🇿🇦"},
    {"name": "Rishi",                  "lang": "en-IN", "flag": "🇮🇳"},
    {"name": "Paulina",                "lang": "es-MX", "flag": "🇲🇽"},
    {"name": "Mónica",                 "lang": "es-ES", "flag": "🇪🇸"},
    {"name": "Flo (English (US))",     "lang": "en-US", "flag": "🇺🇸"},
    {"name": "Sandy (English (US))",   "lang": "en-US", "flag": "🇺🇸"},
    {"name": "Shelley (English (US))", "lang": "en-US", "flag": "🇺🇸"},
    {"name": "Reed (English (US))",    "lang": "en-US", "flag": "🇺🇸"},
    {"name": "Eddy (English (US))",    "lang": "en-US", "flag": "🇺🇸"},
    {"name": "Jorge",                  "lang": "es-ES", "flag": "🇪🇸"},
]
NICE_VOICE_NAMES = [v["name"] for v in NICE_VOICES]


# ── helpers ───────────────────────────────────────────────────────────────────

def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def save_json(path: Path, data):
    """Write JSON atomically (tempfile + os.replace) so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Per-file locks: hold across the full read-modify-write so concurrent requests
# (threadpool workers + the background TTS drainer thread) never interleave and
# lose or corrupt writes to these shared JSON files / in-memory structures.
_registry_lock    = threading.Lock()
_queue_lock       = threading.Lock()
_muted_lock       = threading.Lock()
_inactive_lock     = threading.Lock()
_wake_enabled_lock = threading.Lock()
_attribution_lock = threading.Lock()
_pending_links_lock = threading.Lock()


# ── vortexia integration ──────────────────────────────────────────────────────
#
# Inter-agent messaging (agent inject) and the TTS speak queue are both
# delivered over vortexia (a sibling MQTT broker — see
# ../vortexia/PROTOCOL.md), not AppleScript/TTY injection or `say`. This
# backend is also the port registry vortexia claims its ports from, so we
# resolve vortexia's current MQTT port by reading our own PORTS_FILE rather
# than making an HTTP round-trip to ourselves.
#
# Every vortexia call below fails soft: if vortexia isn't running, we log a
# warning and keep going — :8700 must stay usable even when vortexia is down.

SPEAK_TOPIC = "las/speak"


def _vortexia_mqtt_port() -> int:
    # Precedence lives in vortexia_client.resolve_mqtt_port (port file written
    # by the live broker first, then our registry's latest claim, then 1883) —
    # shared with `las agent listen` so both sides agree on where the broker is.
    return vx.resolve_mqtt_port(load_json(PORTS_FILE, {}))


def _vortexia_publish(topic: str, envelope: dict, retain: bool = False) -> bool:
    """Fire-and-forget publish of one envelope. Fails soft if vortexia is unreachable.

    Inbox messages are plain QoS 1, NOT retained: the broker owns a persistent
    session per agent (client id las-agent-<name>, see vortexia/PROTOCOL.md
    "Mailboxes") and queues every publish while that agent's consumer isn't
    connected — in order, one entry per message. Retaining was the previous
    mechanism and kept only the latest message per recipient (a second inject
    before the first was read overwrote it). `retain=True` is still accepted
    for callers that knowingly want the legacy single-slot behaviour; nothing
    in this backend uses it for inbox traffic anymore.
    """
    try:
        import paho.mqtt.publish as _mqtt_publish
        _mqtt_publish.single(
            topic,
            payload=json.dumps(envelope),
            qos=1,
            retain=retain,
            hostname="localhost",
            port=_vortexia_mqtt_port(),
        )
        return True
    except Exception as exc:
        logger.warning(f"[vortexia] publish to {topic!r} failed (is vortexia running?): {exc}")
        return False


def _vortexia_set_presence_online(name: str) -> bool:
    """One-shot retained presence publish — the CLI/skill 'register' call can't hold
    a persistent MQTT connection open across a session, so we publish the retained
    'online' payload directly instead of keeping a VortexiaClient connected."""
    try:
        import paho.mqtt.publish as _mqtt_publish
        _mqtt_publish.single(
            vx.presence_topic(name),
            payload="online",
            qos=1,
            retain=True,
            hostname="localhost",
            port=_vortexia_mqtt_port(),
        )
        return True
    except Exception as exc:
        logger.warning(f"[vortexia] presence publish for {name!r} failed (is vortexia running?): {exc}")
        return False


def _vortexia_poll_inbox(name: str, timeout: float = 2.0) -> list[dict]:
    """Drain whatever's waiting in `name`'s mailbox. Fails soft (returns []).

    Connects as the mailbox consumer (las-agent-<name>, persistent session)
    just long enough to receive the queued backlog. Stands down with [] when
    a live `las agent listen` already holds that session — it IS the delivery
    path while it runs, and taking the session over would kick it."""
    try:
        return vx.poll_inbox(name, host="localhost", port=_vortexia_mqtt_port(), timeout=timeout)
    except Exception as exc:
        logger.warning(f"[vortexia] poll_inbox for {name!r} failed (is vortexia running?): {exc}")
        return []


# ── TTS drainer (background thread) ──────────────────────────────────────────

def tts_drainer():
    while True:
        with _queue_lock:
            queue = load_json(QUEUE_FILE, [])
            msg = queue.pop(0) if queue else None
            if msg is not None:
                save_json(QUEUE_FILE, queue)
        if msg is None:
            time.sleep(0.4)
            continue
        name = msg.get("name", "")
        with _muted_lock:
            muted = load_json(MUTED_FILE, [])
        if name in muted:
            continue
        voice = msg.get("voice", "Samantha")
        text  = msg.get("text", "")
        if voice not in NICE_VOICE_NAMES:
            print(f"[tts] skipping unknown voice {voice!r} for {name!r}", flush=True)
            continue
        if not text:
            continue
        # Publish to vortexia instead of shelling out to `say`. Whichever
        # Electron widget is running for `name` picks this up off las/speak
        # and does the actual TTS playback (Web Speech API) — see the note
        # appended to vortexia/PROTOCOL.md. Nothing currently produces sound
        # from this path until that widget exists.
        envelope = {
            "from": "queue",
            "to": name,
            "source": "system",
            "kind": "speak",
            "text": text,
            "voice": voice,
            "ts": int(time.time() * 1000),
        }
        _vortexia_publish(SPEAK_TOPIC, envelope)


threading.Thread(target=tts_drainer, daemon=True).start()


# ── models ────────────────────────────────────────────────────────────────────

class AgentRegistration(BaseModel):
    name:          str
    voice:         str
    path:          str
    backend_url:   Optional[str] = "http://localhost:8700"
    frontend_url:  Optional[str] = None
    pronunciation: Optional[str] = None


class PortRegistration(BaseModel):
    port:         int
    app:          str
    local_agent:  str
    path:         str


class PortClaimRequest(BaseModel):
    port:        Optional[int] = None
    app:         str
    local_agent: str
    path:        str
    start:       int = 9000
    end:         int = 9999


class SpeakRequest(BaseModel):
    text:   str = Field(max_length=10000)
    voice:  str
    name:   str


class AttributionEntry(BaseModel):
    file:      str
    agent:     str
    name:      str
    timestamp: str
    project:   str


class RenameRequest(BaseModel):
    new_name:      str
    pronunciation: Optional[str] = None


class InjectRequest(BaseModel):
    message:     str = Field(max_length=10000)
    source:      str           = "voice"   # "voice" | "agent" | "external" | "raw"
    from_agent:  Optional[str] = None
    # `tty` / `queue` are no longer meaningful — delivery is 100% vortexia now
    # (no TTY concept, no local pending-queue file). Kept out of the model on
    # purpose; any caller still sending them (e.g. an unrebuilt widget) is
    # unaffected since pydantic ignores unknown fields by default.


class SendRequest(BaseModel):
    """Generic point-to-point OR scope-broadcast send — see send_message().
    Exactly one of `to`/`scope` must be set; pydantic doesn't express an
    XOR directly, so send_message() itself enforces it."""
    message:     str = Field(max_length=10000)
    to:          Optional[str] = None   # exact id, optionally "name@env"
    scope:       Optional[str] = None   # free-text scope/intent for broadcast
    source:      str           = "agent"
    from_agent:  Optional[str] = None


class TerminalRequest(BaseModel):
    model:    str            = "Default"
    model_id: Optional[str] = None        # claude --model flag value
    bare:     bool           = False       # open plain shell, no claude
    resume:   bool           = False       # run `claude --resume`


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}



@app.get("/voices/random")
def random_voice():
    registry = load_json(REGISTRY_FILE, {})
    taken = {v["voice"] for v in registry.values() if "voice" in v}
    available = [v["name"] for v in NICE_VOICES if v["name"] not in taken]
    if not available:
        available = NICE_VOICE_NAMES  # pool exhausted — allow repeats
    return {"voice": random.choice(available)}


@app.get("/voices")
def list_voices():
    return {"voices": NICE_VOICES}


@app.get("/voices/{name}")
def get_voice(name: str):
    voice = next((v for v in NICE_VOICES if v["name"] == name), None)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")
    return voice


# ── local text-to-speech (Kokoro-82M via kokoro-onnx) ───────────────────────
#
# widget-electron used to run Kokoro in-process (kokoro-js, in Electron's
# main/Node process). That broke when packaged: electron-builder's own
# native-module rebuild step re-flattens node_modules, collapsing the
# onnxruntime-common version Kokoro needs back down to the older one Whisper
# (@xenova/transformers) pins, which crashes Kokoro's tokenizer at runtime.
# Moving synthesis here sidesteps that packaging conflict entirely — one
# Python process, one onnxruntime — and as a bonus, kokoro-onnx's espeak-ng
# phonemizer is a real native binary (via espeakng-loader), not the WASM
# build kokoro-js uses, which is what made Spanish voices (ef_/em_) crash in
# Node but work fine here.
#
# Model files are NOT bundled in the repo (~340MB) — download once with:
#   curl -L -o backend/data/kokoro/kokoro-v1.0.onnx \
#     https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
#   curl -L -o backend/data/kokoro/voices-v1.0.bin \
#     https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
KOKORO_DIR = DATA_DIR / "kokoro"
KOKORO_MODEL_PATH = KOKORO_DIR / "kokoro-v1.0.onnx"
KOKORO_VOICES_PATH = KOKORO_DIR / "voices-v1.0.bin"

_kokoro = None
_kokoro_lock = threading.Lock()


def get_kokoro():
    """Lazily create (and memoize) the Kokoro instance — first call pays
    model-load time, every call after is just inference."""
    global _kokoro
    if _kokoro is None:
        with _kokoro_lock:
            if _kokoro is None:
                from kokoro_onnx import Kokoro
                logger.info(f"tts: loading kokoro model from {KOKORO_MODEL_PATH}")
                _kokoro = Kokoro(str(KOKORO_MODEL_PATH), str(KOKORO_VOICES_PATH))
                logger.info("tts: kokoro model loaded")
    return _kokoro


class TTSRequest(BaseModel):
    text: str
    voice: str = "af_heart"
    lang: str = "en-us"
    speed: float = 1.0


@app.post("/tts/synthesize")
def tts_synthesize(req: TTSRequest):
    if not KOKORO_MODEL_PATH.exists() or not KOKORO_VOICES_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Kokoro model files not found under {KOKORO_DIR} — see the download instructions in main.py",
        )
    try:
        kokoro = get_kokoro()
        samples, sample_rate = kokoro.create(req.text, voice=req.voice, speed=req.speed, lang=req.lang)
    except Exception as e:
        logger.error(f"tts: synthesis failed (voice={req.voice!r} lang={req.lang!r}): {e}")
        raise HTTPException(status_code=500, detail=str(e))
    import io
    import soundfile as sf
    from fastapi.responses import Response as FastResponse
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return FastResponse(content=buf.getvalue(), media_type="audio/wav")


# ── agents ────────────────────────────────────────────────────────────────────

@app.get("/agents")
def list_agents():
    with _registry_lock:
        registry = load_json(REGISTRY_FILE, {})
    with _inactive_lock:
        inactive = load_json(INACTIVE_FILE, [])
    with _wake_enabled_lock:
        wake_enabled = load_json(WAKE_ENABLED_FILE, [])
    return {
        name: {**info, "inactive": name in inactive, "wake_enabled": name in wake_enabled}
        for name, info in registry.items()
    }


@app.post("/agents")
def register_agent(agent: AgentRegistration):
    with _registry_lock:
        registry = load_json(REGISTRY_FILE, {})
        data = agent.model_dump()
        data["backend_url"] = "http://localhost:8700"
        data["frontend_url"] = f"http://localhost:8700/widget/{agent.name}"
        registry[agent.name] = {**data, "registered_at": datetime.now().isoformat()}
        save_json(REGISTRY_FILE, registry)
    return {"ok": True, "name": agent.name}


@app.delete("/agents/{name}")
def unregister_agent(name: str):
    with _registry_lock:
        registry = load_json(REGISTRY_FILE, {})
        if name not in registry:
            raise HTTPException(status_code=404, detail="Agent not found")
        del registry[name]
        save_json(REGISTRY_FILE, registry)
    return {"ok": True}


@app.get("/agents/{name}/hierarchy")
def agent_hierarchy(name: str, deep: bool = False):
    """Parent and subordinates of `name`, derived purely from registered paths.

    The folders are the source of truth: an agent registered under another
    agent's path is its subordinate. Nothing is declared in .las-agent.json
    (see cli/hierarchy.py). `deep=true` lists every descendant instead of
    only direct children."""
    from cli.hierarchy import children_of, parent_of
    with _registry_lock:
        registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    children = children_of(name, registry, deep=deep)
    return {
        "name": name,
        "path": registry[name].get("path"),
        "parent": parent_of(name, registry),
        "children": [
            {"name": c, "path": registry[c].get("path"), "voice": registry[c].get("voice")}
            for c in children
        ],
        "deep": deep,
    }


@app.patch("/agents/{name}")
def rename_agent(name: str, body: RenameRequest):
    with _registry_lock:
        registry = load_json(REGISTRY_FILE, {})
        if name not in registry:
            raise HTTPException(status_code=404, detail="Agent not found")
        new_name = body.new_name.strip()
        if not new_name:
            raise HTTPException(status_code=422, detail="new_name must not be empty")
        if new_name in registry and new_name != name:
            raise HTTPException(status_code=409, detail=f"Agent '{new_name}' already exists")
        entry = registry.pop(name)
        entry["name"] = new_name
        entry["frontend_url"] = f"http://localhost:8700/widget/{new_name}"
        if body.pronunciation is not None:
            entry["pronunciation"] = body.pronunciation
        elif entry.get("pronunciation") == name:
            entry["pronunciation"] = new_name
        registry[new_name] = entry
        save_json(REGISTRY_FILE, registry)
    return {"ok": True, "old_name": name, "new_name": new_name}


# Pending TTY links registered via `las link` CLI command
_pending_links: dict[str, str] = {}

_ports_lock = threading.Lock()


def _port_is_free(port: int, registered: set) -> bool:
    if port in registered:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0


# ── ports ─────────────────────────────────────────────────────────────────────

@app.get("/ports")
def list_ports():
    return load_json(PORTS_FILE, {})


@app.post("/ports")
def register_port(reg: PortRegistration):
    ports = load_json(PORTS_FILE, {})
    ports[str(reg.port)] = {
        **reg.model_dump(),
        "registered_at": datetime.now().isoformat(),
    }
    save_json(PORTS_FILE, ports)
    return {"ok": True, "port": reg.port}


@app.delete("/ports/{port}")
def unregister_port(port: int):
    ports = load_json(PORTS_FILE, {})
    if str(port) not in ports:
        raise HTTPException(status_code=404, detail="Port not registered")
    del ports[str(port)]
    save_json(PORTS_FILE, ports)
    return {"ok": True}


@app.get("/ports/free")
def get_free_port(start: int = 9000, end: int = 9999):
    with _ports_lock:
        ports = load_json(PORTS_FILE, {})
        registered = {int(k) for k in ports.keys()}
        for port in range(start, end + 1):
            if _port_is_free(port, registered):
                return {"port": port}
    raise HTTPException(status_code=503, detail="No free ports available")


@app.post("/ports/claim")
def claim_port(req: PortClaimRequest):
    with _ports_lock:
        ports = load_json(PORTS_FILE, {})
        registered = {int(k) for k in ports.keys()}

        if req.port is not None:
            if not _port_is_free(req.port, registered):
                raise HTTPException(status_code=409, detail=f"Port {req.port} is already taken")
            chosen = req.port
        else:
            chosen = None
            for p in range(req.start, req.end):
                if _port_is_free(p, registered):
                    chosen = p
                    break
            if chosen is None:
                raise HTTPException(status_code=503, detail="No free ports available in range")

        # A re-claim from the same app+local_agent supersedes its earlier
        # claim(s) — without this, a service that restarts onto a new port
        # (e.g. vortexia finding its old port occupied) leaves its dead old
        # entry in the registry forever, and any lookup that isn't careful
        # about picking the most recent one keeps targeting the dead port.
        stale = [
            port for port, info in ports.items()
            if info.get("app") == req.app and info.get("local_agent") == req.local_agent
            and port != str(chosen)
        ]
        for port in stale:
            del ports[port]

        ports[str(chosen)] = {
            "port": chosen,
            "app": req.app,
            "local_agent": req.local_agent,
            "path": req.path,
            "registered_at": datetime.now().isoformat(),
        }
        save_json(PORTS_FILE, ports)
        return {"port": chosen}


# ── TTS queue ─────────────────────────────────────────────────────────────────

@app.post("/queue/speak")
def enqueue_speak(req: SpeakRequest):
    with _queue_lock:
        queue = load_json(QUEUE_FILE, [])
        queue.append({"text": req.text, "voice": req.voice, "name": req.name})
        save_json(QUEUE_FILE, queue)
        length = len(queue)
    return {"ok": True, "queue_length": length}


@app.get("/queue")
def get_queue():
    with _queue_lock:
        return load_json(QUEUE_FILE, [])


@app.delete("/queue")
def clear_queue():
    with _queue_lock:
        save_json(QUEUE_FILE, [])
    return {"ok": True}


# ── agent inject ─────────────────────────────────────────────────────────────
# Delivery is 100% vortexia now (see the "vortexia integration" section
# above) — no AppleScript/TTY injection, no on-disk pending-message queue.
# The old file-based pending queue (session/pending-injects.json, drained
# into a live TTY on the next inject) is gone; vortexia's own inbox is the
# queue now, drained via GET /agents/{name}/vortexia/poll (see below).

from cli.path_utils import find_nearest_agent_dir as _find_nearest_agent_dir


def _claude_pids_for_path(agent_path: str) -> list[str]:
    """Return PIDs of all claude processes whose nearest .agent.json matches agent_path."""
    try:
        ps_out = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="], capture_output=True, text=True, timeout=5
        ).stdout
        pids = []
        for line in ps_out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            pid, cmd = parts
            if pid.isdigit() and "claude" in cmd and "Claude.app" not in cmd:
                pids.append(pid)
        matched = []
        for pid in pids:
            lsof_out = subprocess.run(
                ["/usr/sbin/lsof", "-p", pid, "-a", "-d", "cwd"],
                capture_output=True, text=True, timeout=5
            ).stdout
            for line in lsof_out.splitlines()[1:]:
                parts = line.split()
                if not parts:
                    continue
                cwd = parts[-1]
                nearest = _find_nearest_agent_dir(cwd)
                if nearest == agent_path:
                    matched.append(pid)
                    break
        return matched
    except Exception:
        return []


def _find_claude_tty(agent_path: str) -> str | None:
    """Find the TTY of the first claude process whose cwd is agent_path."""
    for pid in _claude_pids_for_path(agent_path):
        try:
            tty = subprocess.run(
                ["ps", "-p", pid, "-o", "tty="],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if tty and tty != "??":
                return tty
        except Exception:
            continue
    return None


def _find_all_claude_ttys(agent_path: str) -> list[str]:
    """Return ALL TTYs of claude processes whose cwd is agent_path (deduplicated, ordered)."""
    seen: list[str] = []
    for pid in _claude_pids_for_path(agent_path):
        try:
            ps_out = subprocess.run(
                ["ps", "-p", pid, "-o", "tty=,comm="],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()
            parts = ps_out.split(None, 1)
            tty  = parts[0] if parts else ""
            comm = parts[1] if len(parts) > 1 else ""
            print(f"[ttys] path={agent_path!r} pid={pid} tty={tty!r} comm={comm!r}", flush=True)
            if tty and tty != "??" and tty not in seen:
                seen.append(tty)
        except Exception:
            continue
    return seen


# Strict TTY device path format — guards every AppleScript path that interpolates a tty.
TTY_RE = re.compile(r"^/dev/ttys\d{3,4}$")


def _run_osascript_with_argv(script: str, args: list[str], timeout: int = 4) -> subprocess.CompletedProcess:
    """Run an AppleScript ("on run argv ...") from a short-lived temp file, passing
    `args` as argv so untrusted text is never interpolated into the script source."""
    fd, tmp_path = tempfile.mkstemp(suffix=".applescript")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(script)
        return subprocess.run(
            ["osascript", tmp_path, *args], capture_output=True, text=True, timeout=timeout
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _inject_via_iterm(tty: str, message: str) -> dict:
    tty_dev = tty if tty.startswith("/") else f"/dev/{tty}"
    delay_s = round(min(0.05 + len(message) * 0.002, 1.0), 3)
    # `message` is passed as argv item 1, never interpolated into the script source.
    script = f'''
on run argv
    set msg to item 1 of argv
    set foundIt to false
    set sessionCount to 0
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    set sessionCount to sessionCount + 1
                    try
                        if (tty of s) is equal to "{tty_dev}" then
                            tell s
                                write text msg newline NO
                                delay {delay_s}
                                write text (ASCII character 13) newline NO
                            end tell
                            set foundIt to true
                        end if
                    end try
                end repeat
            end repeat
        end repeat
    end tell
    if foundIt then
        return "ok|sessions=" & sessionCount
    end if
    return "not_found|sessions=" & sessionCount
end run
'''
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    try:
        result = _run_osascript_with_argv(script, [message], timeout=4)
        success = result.returncode == 0 and "ok" in result.stdout
        return {
            "success": success,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "ts": ts,
            "delay_s": delay_s,
            "text_len": len(message),
            "tty": tty_dev,
        }
    except Exception as exc:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "ts": ts,
            "delay_s": delay_s,
            "text_len": len(message),
            "tty": tty_dev,
        }


def _focus_via_iterm(tty: str) -> dict:
    tty_dev = tty if tty.startswith("/") else f"/dev/{tty}"
    script = f'''
set foundIt to false
set sessionCount to 0
set seenTTYs to ""
tell application "iTerm2"
    set winCount to count of windows
    repeat with wi from 1 to winCount
        set tabCount to count of tabs of window wi
        repeat with ti from 1 to tabCount
            set sesCount to count of sessions of tab ti of window wi
            repeat with si from 1 to sesCount
                set sessionCount to sessionCount + 1
                set sessionTty to ""
                try
                    set sessionTty to tty of session si of tab ti of window wi
                    set seenTTYs to seenTTYs & sessionTty & "|"
                end try
                if sessionTty contains "{tty}" then
                    set foundIt to true
                    -- capture references before reordering (index shifts after set index)
                    set theWin to window wi
                    set theTab to tab ti of theWin
                    set theSes to session si of theTab
                    set index of theWin to 1
                    -- NOT "set current tab of theWin to theTab" — that raises
                    -- "AppleEvent handler failed (-10000)" on this iTerm2
                    -- version (reproduced directly via osascript). Selecting
                    -- the session already switches to its parent tab per
                    -- iTerm2's own scripting dictionary, so the explicit
                    -- current-tab assignment was both redundant and broken.
                    tell theSes to select
                    activate
                    return "ok|sessions=" & sessionCount & "|ttys=" & seenTTYs
                end if
            end repeat
        end repeat
    end repeat
end tell
if foundIt then
    return "ok|sessions=" & sessionCount & "|ttys=" & seenTTYs
end if
return "not_found|sessions=" & sessionCount & "|ttys=" & seenTTYs
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=4
        )
        success = result.returncode == 0 and "ok" in result.stdout
        return {
            "success": success,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "tty": tty_dev,
        }
    except Exception as exc:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "tty": tty_dev,
        }


@app.post("/agents/{name}/focus")
def focus_agent_terminal(name: str):
    """Bring the agent's iTerm2 window/tab/session to the foreground.

    Wake-via-vortexia fallback: if no live session is found AND the agent is
    both inactive and opted into wake-enabled, open a fresh iTerm2 window
    running `claude --dangerously-skip-permissions` in its directory instead
    of just reporting "not found", and mark it active again. Both flags must
    be set (see set_inactive/set_wake_enabled) — this must never fire for an
    agent that merely doesn't have iTerm2 open right now for some unrelated
    reason.
    """
    registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    path = registry[name].get("path", "")
    ttys = _find_all_claude_ttys(path)
    print(f"[focus] agent={name} path={path} ttys={ttys}", flush=True)
    for tty in ttys:
        result = _focus_via_iterm(tty)
        print(f"[focus]   tty={tty} success={result['success']} stdout={result['stdout']!r}", flush=True)
        if result["success"]:
            return {"ok": True, "focused": True, "woke": False, "tty": result["tty"], "ttys_found": len(ttys)}

    with _inactive_lock:
        is_inactive = name in load_json(INACTIVE_FILE, [])
    with _wake_enabled_lock:
        wake_enabled = name in load_json(WAKE_ENABLED_FILE, [])
    if not ttys and is_inactive and wake_enabled and path:
        shell_cmd = f"cd {shlex.quote(path)} && claude --dangerously-skip-permissions"
        result = _open_iterm_window(shell_cmd)
        if result.returncode == 0:
            with _inactive_lock:
                inactive = load_json(INACTIVE_FILE, [])
                if name in inactive:
                    inactive.remove(name)
                    save_json(INACTIVE_FILE, inactive)
            print(f"[focus] agent={name} woke via vortexia (opened new iTerm2 window)", flush=True)
            return {"ok": True, "focused": False, "woke": True, "tty": "new window", "ttys_found": 0}
        print(f"[focus] agent={name} wake failed: {result.stderr.strip()}", flush=True)

    return {"ok": True, "focused": False, "woke": False, "tty": ttys[0] if ttys else "not found", "ttys_found": len(ttys)}


@app.get("/debug/iterm_ttys")
def debug_iterm_ttys():
    """List all TTYs currently known to iTerm2 via AppleScript."""
    # `result` shadows AppleScript's own implicit `result` variable (holds
    # the value of the last executed statement) — using it as a normal list
    # broke `set end of result to ...` with "Can't set end of ... (-10006)",
    # reproduced directly via osascript. Renamed to `ttyList`.
    script = """
set ttyList to {}
tell application "iTerm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                set end of ttyList to (tty of s)
            end repeat
        end repeat
    end repeat
end tell
return ttyList
"""
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
    raw = out.stdout.strip()
    ttys = [t.strip() for t in raw.split(",") if t.strip()]
    return {"iterm_ttys": ttys, "count": len(ttys)}


def _open_iterm_window(shell_cmd: str) -> subprocess.CompletedProcess:
    """Open a new iTerm2 window running `shell_cmd`, then drop into an
    interactive login shell so the window stays open after it exits. Shared
    by open_terminal and focus_agent_terminal's wake-via-vortexia fallback —
    same osascript both callers used to build independently."""
    user_shell = os.environ.get("SHELL", "/bin/zsh")
    script = (
        'tell application "iTerm2"\n'
        f'    create window with default profile command "{user_shell} -l -c \'{shell_cmd}; exec {user_shell} -l\'"\n'
        'end tell'
    )
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)


@app.post("/agents/{name}/terminal")
def open_terminal(name: str, body: TerminalRequest):
    """Open a new iTerm2 window running claude in the agent's directory."""
    registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    path = registry[name].get("path", "")
    if body.resume:
        shell_cmd = f"cd {shlex.quote(path)} && claude --resume"
    elif body.bare:
        shell_cmd = f"cd {shlex.quote(path)}"
    else:
        claude_cmd = f"claude --model {body.model_id}" if body.model_id else "claude"
        shell_cmd = f"cd {shlex.quote(path)} && {claude_cmd}"
    result = _open_iterm_window(shell_cmd)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"osascript error: {result.stderr.strip()}")
    return {"ok": True, "model": body.model}


@app.get("/agents/{name}/ttys")
def get_agent_ttys(name: str):
    registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    path = registry[name].get("path", "")
    return {"ttys": _find_all_claude_ttys(path)}


class TtyWriteRequest(BaseModel):
    text: str = Field(max_length=10000)
    tty:  Optional[str] = None  # write to this one TTY only; omit to write to all found


@app.post("/agents/{name}/tty-write")
def write_to_tty(name: str, body: TtyWriteRequest):
    """Type `text` directly into the agent's live iTerm2 session(s) — raw
    terminal injection via _inject_via_iterm, NOT vortexia messaging. This is
    the mechanism the widget's Clear button used (typing a literal "/clear")
    before the inter-agent inject pipeline was migrated to vortexia; that
    migration only retired cross-agent *messaging*, not this local
    "type into my own linked terminal" action, which still works exactly as
    before (mac-only, via iTerm2 AppleScript).

    An agent can have more than one live terminal open at once (see
    _find_all_claude_ttys) — with no `tty` given, this writes to ALL of them.
    """
    registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    path = registry[name].get("path", "")
    ttys = [body.tty] if body.tty else _find_all_claude_ttys(path)
    results = [_inject_via_iterm(tty, body.text) for tty in ttys]
    written = [r["tty"] for r in results if r["success"]]
    return {"ok": True, "written": written, "ttys_found": len(ttys)}


def _route_send(*, to: str | None, scope: str | None, message: str, source: str, sender: str) -> dict:
    """Single delivery path for both /agents/send and the legacy
    /agents/{name}/inject — one implementation, two request shapes on top
    of it (DRY: this used to be duplicated between the two endpoints).

    Exactly one of `to` (point-to-point) or `scope` (broadcast, possibly
    multiple agents respond — see VortexRelayBridge._onLocalMessage's
    pickTargets in vortexia/src/vortex-relay/bridge.js) must be given; the
    caller validates that, not this function.

    - `to="Name"` — local registry lookup first (unqualified names only;
      "Name@env" always skips straight to vortex-relay, since a local
      registry entry can't be qualified). Falls back to a vortex-relay-direct
      publish (kind=vortex-relay-direct) to this environment's own gateway
      inbox when not found locally, or when explicitly qualified with
      "Name@env" to disambiguate a collision (two environments with an
      agent of the same name) — see resolveDirectoryName in
      vortexia/src/vortex-relay/directory.js.
    - `scope="free text"` — always goes through the gateway as a
      vortex-relay-intent envelope; there's no local-only equivalent of
      scope/embedding-based matching outside the bridge, so this mode
      requires VORTEXIA_ENV_NAME regardless of whether the eventual
      match(es) turn out to be local or remote. Zero, one, or several
      agents may reply — each reply is just a normal message back to the
      sender, no separate fan-in mechanism.

    Delivery is fire-and-forget in every case: a vortex-relay-direct send to
    an unresolvable name comes back as an async `vortex-relay-direct-error`
    reply to the sender, not a synchronous failure here — this can't tell
    "wrong name" apart from "right name, recipient just hasn't polled yet"
    any more than a local send ever could.

    Vortex-relay-direct/intent publishes are non-retained (unlike the local
    case): the gateway is a live, always-connected process supervised by
    launchd, not a session that polls later (see
    docs/adr/0002-service-persistence-and-logging.md) — and unlike
    `las agent listen`/poll_inbox, nothing on the bridge side clears a
    retained flag on receipt, so a retained publish here would replay into
    the bridge on every vortexia restart.

    Returns {ok, injected, mode: "direct"|"scope", relayed}. Raises
    HTTPException on a configuration error (no `to`/`scope` resolution
    possible without vortex-relay).
    """
    ts = int(time.time() * 1000)
    env_name = os.environ.get("VORTEXIA_ENV_NAME")

    if scope:
        if not env_name:
            raise HTTPException(status_code=400, detail="scope broadcast requires vortex-relay to be configured (VORTEXIA_ENV_NAME)")
        envelope = {"from": sender, "intent": scope, "text": message, "kind": "vortex-relay-intent", "ts": ts}
        delivered = _vortexia_publish(vx.inbox_topic(f"{env_name}-gateway"), envelope, retain=False)
        return {"ok": True, "injected": delivered, "mode": "scope", "relayed": True}

    registry = load_json(REGISTRY_FILE, {})
    if "@" not in to and to in registry:
        envelope = {"from": sender, "to": to, "source": source, "text": message, "ts": ts}
        # Not retained: the broker's mailbox for `to` queues it if nobody is
        # connected as its consumer (see _vortexia_publish).
        delivered = _vortexia_publish(vx.inbox_topic(to), envelope, retain=False)

        # ── structured inject log (local delivery only — a vortex-relayed `to`
        # has no local registry entry, so no session/ dir to log into) ──
        path = registry.get(to, {}).get("path", "")
        log_path = Path(path) / "session" / "inject.log"
        if log_path.parent.exists():
            ts_full = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            preview = message[:60].replace("\n", " ") + ("…" if len(message) > 60 else "")
            status  = "OK" if delivered else "FAIL(vortexia unreachable)"
            with open(log_path, "a") as f:
                f.write(f"[{ts_full}] name={to} source={source} from={sender} via=vortexia status={status} msg={preview!r}\n")

        return {"ok": True, "injected": delivered, "mode": "direct", "relayed": False}

    if not env_name:
        raise HTTPException(status_code=404, detail="Agent not found (and vortex-relay not configured on this machine)")
    envelope = {"from": sender, "to": to, "source": source, "text": message, "kind": "vortex-relay-direct", "ts": ts}
    delivered = _vortexia_publish(vx.inbox_topic(f"{env_name}-gateway"), envelope, retain=False)
    return {"ok": True, "injected": delivered, "mode": "direct", "relayed": True}


@app.post("/agents/send")
def send_message(body: SendRequest):
    """Generic send: point-to-point (`to`) or scope broadcast (`scope`),
    local or cross-machine — see _route_send for the routing rules. This
    is the primitive `las agent send` calls; /agents/{name}/inject below
    is a thin backward-compatible wrapper over the same logic."""
    if bool(body.to) == bool(body.scope):
        raise HTTPException(status_code=422, detail="exactly one of `to` or `scope` must be set")
    sender = body.from_agent or body.source or "external"
    return _route_send(to=body.to, scope=body.scope, message=body.message, source=body.source, sender=sender)


@app.post("/agents/{name}/inject")
def inject_message(name: str, body: InjectRequest):
    """Send a message to `name` over vortexia. Kept for existing callers
    (every agent's las-agent skill still says `las agent inject`) — thin
    wrapper over the same _route_send logic /agents/send uses, reshaped to
    inject's original response fields for backward compatibility."""
    sender = body.from_agent or body.source or "external"
    result = _route_send(to=name, scope=None, message=body.message, source=body.source, sender=sender)
    # inject's own response shape keeps the "federated" field name for
    # backward compatibility with existing callers — only _route_send's
    # internal field was renamed to "relayed".
    return {"ok": True, "injected": result["injected"], "queued": False, "via": "vortexia", "federated": result["relayed"]}


@app.post("/agents/{name}/vortexia/register")
def vortexia_register(name: str):
    """Called by the /las-agent skill at session start. Publishes a retained
    'online' presence payload for `name` on vortexia (las/agent/<name>/presence).

    This is a one-shot publish, not a persistent VortexiaClient.register()
    connection — a freshly-invoked `las` CLI process can't stay connected for
    the life of a Claude Code session, so there's no LWT here. Presence just
    reflects "was seen recently", not "is connected right now".
    """
    registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    ok = _vortexia_set_presence_online(name)
    return {"ok": True, "registered": ok, "via": "vortexia"}


@app.get("/agents/{name}/vortexia/poll")
def vortexia_poll(name: str, timeout: float = 2.0):
    """Drain `name`'s mailbox for up to `timeout` seconds and return whatever
    was queued. Called by the /las-agent skill at session start. Returns
    count 0 without draining when a live `las agent listen` holds the mailbox
    session (see _vortexia_poll_inbox)."""
    registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    timeout = max(0.1, min(timeout, 10.0))
    messages = _vortexia_poll_inbox(name, timeout=timeout)
    return {"count": len(messages), "messages": messages}


# ── agent mute ────────────────────────────────────────────────────────────────

@app.post("/agents/{name}/mute")
def mute_agent(name: str):
    with _muted_lock:
        muted = load_json(MUTED_FILE, [])
        if name not in muted:
            muted.append(name)
            save_json(MUTED_FILE, muted)
    return {"ok": True, "muted": True, "name": name}


@app.delete("/agents/{name}/mute")
def unmute_agent(name: str):
    with _muted_lock:
        muted = load_json(MUTED_FILE, [])
        if name in muted:
            muted.remove(name)
            save_json(MUTED_FILE, muted)
    return {"ok": True, "muted": False, "name": name}


@app.get("/agents/{name}/muted")
def get_muted(name: str):
    with _muted_lock:
        muted = load_json(MUTED_FILE, [])
    return {"muted": name in muted, "name": name}


# ── agent inactive/active ──────────────────────────────────────────────────────
# "Inactive" marks an agent as put away — the widget's door button and
# `las agent deactivate` set this and close the widget; it does not touch the
# registry entry or kill any running Claude Code session, it's purely a
# visibility/status flag consulted by `las agents` (to list/filter) and by
# focus_agent_terminal's wake fallback below.

@app.post("/agents/{name}/inactive")
def set_inactive(name: str):
    with _inactive_lock:
        inactive = load_json(INACTIVE_FILE, [])
        if name not in inactive:
            inactive.append(name)
            save_json(INACTIVE_FILE, inactive)
    return {"ok": True, "inactive": True, "name": name}


@app.delete("/agents/{name}/inactive")
def clear_inactive(name: str):
    with _inactive_lock:
        inactive = load_json(INACTIVE_FILE, [])
        if name in inactive:
            inactive.remove(name)
            save_json(INACTIVE_FILE, inactive)
    return {"ok": True, "inactive": False, "name": name}


@app.get("/agents/{name}/inactive")
def get_inactive(name: str):
    with _inactive_lock:
        inactive = load_json(INACTIVE_FILE, [])
    return {"inactive": name in inactive, "name": name}


# ── wake-up via vortexia (opt-in per agent) ────────────────────────────────────
# When enabled, an inactive agent with no live terminal session gets woken up
# by focus_agent_terminal below instead of just reporting "not found": a new
# iTerm2 window is opened running `claude --dangerously-skip-permissions` in
# its registered directory, and the agent is marked active again. Off by
# default — waking a session unattended is exactly the kind of thing that
# should require an explicit opt-in per agent.

@app.post("/agents/{name}/wake-enabled")
def set_wake_enabled(name: str):
    with _wake_enabled_lock:
        enabled = load_json(WAKE_ENABLED_FILE, [])
        if name not in enabled:
            enabled.append(name)
            save_json(WAKE_ENABLED_FILE, enabled)
    return {"ok": True, "wake_enabled": True, "name": name}


@app.delete("/agents/{name}/wake-enabled")
def clear_wake_enabled(name: str):
    with _wake_enabled_lock:
        enabled = load_json(WAKE_ENABLED_FILE, [])
        if name in enabled:
            enabled.remove(name)
            save_json(WAKE_ENABLED_FILE, enabled)
    return {"ok": True, "wake_enabled": False, "name": name}


@app.get("/agents/{name}/wake-enabled")
def get_wake_enabled(name: str):
    with _wake_enabled_lock:
        enabled = load_json(WAKE_ENABLED_FILE, [])
    return {"wake_enabled": name in enabled, "name": name}


# ── terminal link (drag-to-link via `las link`) ───────────────────────────────

@app.post("/agents/{name}/pin-tty")
def pin_tty(name: str, body: dict):
    """Store a TTY linked via `las link` for the widget to pick up."""
    tty = body.get("tty", "")
    if tty:
        with _pending_links_lock:
            _pending_links[name] = tty
    return {"ok": bool(tty), "tty": tty}


@app.get("/agents/{name}/pending-link")
def get_pending_link(name: str):
    """Return and clear the pending linked TTY for an agent (consumed once)."""
    from fastapi.responses import Response as FastResponse
    with _pending_links_lock:
        tty = _pending_links.pop(name, None)
    if tty:
        return {"tty": tty}
    return FastResponse(status_code=204)


# ── attribution ───────────────────────────────────────────────────────────────

@app.post("/attribution")
def record_attribution(entry: AttributionEntry):
    with _attribution_lock:
        log = load_json(ATTRIBUTION_FILE, [])
        log.append(entry.model_dump())
        save_json(ATTRIBUTION_FILE, log)
    return {"ok": True}


@app.get("/attribution")
def get_attribution(file: str = None, name: str = None):
    with _attribution_lock:
        log = load_json(ATTRIBUTION_FILE, [])
    if file:
        log = [e for e in log if e["file"] == file]
    if name:
        log = [e for e in log if e["name"] == name]
    return log


# ── widget ────────────────────────────────────────────────────────────────────

@app.get("/widget/{name}", response_class=HTMLResponse)
def widget(name: str):
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{name}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: rgba(144,192,96,0.90);
    font-family: -apple-system, 'Helvetica Neue', Helvetica, sans-serif;
    width: 300px; height: 160px;
    display: flex; flex-direction: column;
    justify-content: center; align-items: flex-start;
    padding: 18px 24px;
    border-radius: 4px;
    overflow: hidden;
    user-select: none;
  }}
  .name {{
    font-size: 68px; font-weight: 900;
    color: #1a1a1a; line-height: 1;
    letter-spacing: -2px;
  }}
</style>
</head>
<body>
  <div class="name">{name}</div>
</body>
</html>"""
