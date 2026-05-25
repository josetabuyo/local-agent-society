"""
Local Agent Society — Backend
Port: 8700
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import json
import subprocess
import threading
import time
import random
import socket
from pathlib import Path
from datetime import datetime

app = FastAPI(title="Local Agent Society", version="1.0.0")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

REGISTRY_FILE = DATA_DIR / "registry.json"
QUEUE_FILE    = DATA_DIR / "queue.json"
PORTS_FILE       = DATA_DIR / "ports.json"
ATTRIBUTION_FILE = DATA_DIR / "attribution.json"

NICE_VOICES = [
    "Samantha", "Daniel", "Moira", "Karen", "Tessa", "Rishi",
    "Paulina", "Mónica", "Flo (English (US))", "Sandy (English (US))",
    "Shelley (English (US))", "Reed (English (US))", "Eddy (English (US))",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── TTS drainer (background thread) ──────────────────────────────────────────

def tts_drainer():
    while True:
        queue = load_json(QUEUE_FILE, [])
        if queue:
            msg = queue.pop(0)
            save_json(QUEUE_FILE, queue)
            voice = msg.get("voice", "Samantha")
            text  = msg.get("text", "")
            if text:
                subprocess.run(["say", "-v", voice, text], check=False)
        else:
            time.sleep(0.4)


threading.Thread(target=tts_drainer, daemon=True).start()


# ── models ────────────────────────────────────────────────────────────────────

class AgentRegistration(BaseModel):
    family:       str
    role:         str
    voice:        str
    path:         str
    backend_url:  str
    frontend_url: str
    members:      list[str]


class PortRegistration(BaseModel):
    port:         int
    app:          str
    agent_family: str
    path:         str


class SpeakRequest(BaseModel):
    text:   str
    voice:  str
    family: str


class AttributionEntry(BaseModel):
    file:      str
    agent:     str
    family:    str
    timestamp: str
    project:   str


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.get("/voices/random")
def random_voice():
    registry = load_json(REGISTRY_FILE, {})
    taken = {v["voice"] for v in registry.values() if "voice" in v}
    available = [v for v in NICE_VOICES if v not in taken]
    if not available:
        available = NICE_VOICES  # pool exhausted — allow repeats
    return {"voice": random.choice(available)}


@app.get("/voices")
def list_voices():
    return {"voices": NICE_VOICES}


# ── agents ────────────────────────────────────────────────────────────────────

@app.get("/agents")
def list_agents():
    return load_json(REGISTRY_FILE, {})


@app.post("/agents")
def register_agent(agent: AgentRegistration):
    registry = load_json(REGISTRY_FILE, {})
    registry[agent.family] = {
        **agent.model_dump(),
        "registered_at": datetime.now().isoformat(),
    }
    save_json(REGISTRY_FILE, registry)
    return {"ok": True, "family": agent.family}


@app.delete("/agents/{family}")
def unregister_agent(family: str):
    registry = load_json(REGISTRY_FILE, {})
    if family not in registry:
        raise HTTPException(status_code=404, detail="Agent family not found")
    del registry[family]
    save_json(REGISTRY_FILE, registry)
    return {"ok": True}


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
    ports = load_json(PORTS_FILE, {})
    registered = {int(k) for k in ports.keys()}
    for port in range(start, end):
        if port in registered:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("localhost", port)) != 0:
                return {"port": port}
    raise HTTPException(status_code=503, detail="No free ports available")


# ── TTS queue ─────────────────────────────────────────────────────────────────

@app.post("/queue/speak")
def enqueue_speak(req: SpeakRequest):
    queue = load_json(QUEUE_FILE, [])
    queue.append({"text": req.text, "voice": req.voice, "family": req.family})
    save_json(QUEUE_FILE, queue)
    return {"ok": True, "queue_length": len(queue)}


@app.get("/queue")
def get_queue():
    return load_json(QUEUE_FILE, [])


@app.delete("/queue")
def clear_queue():
    save_json(QUEUE_FILE, [])
    return {"ok": True}


# ── attribution ───────────────────────────────────────────────────────────────

@app.post("/attribution")
def record_attribution(entry: AttributionEntry):
    log = load_json(ATTRIBUTION_FILE, [])
    log.append(entry.model_dump())
    save_json(ATTRIBUTION_FILE, log)
    return {"ok": True}


@app.get("/attribution")
def get_attribution(file: str = None, family: str = None):
    log = load_json(ATTRIBUTION_FILE, [])
    if file:
        log = [e for e in log if e["file"] == file]
    if family:
        log = [e for e in log if e["family"] == family]
    return log


# ── widget HTML ───────────────────────────────────────────────────────────────

@app.get("/widget/{family}", response_class=HTMLResponse)
def widget(family: str):
    registry = load_json(REGISTRY_FILE, {})
    agent = registry.get(family, {})
    members = agent.get("members", ["sonnet"])
    members_label = " · ".join(m.upper() for m in members)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{family}</title>
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
  .members {{
    font-size: 11px; font-weight: 500;
    color: rgba(0,0,0,0.42);
    margin-top: 8px; letter-spacing: 1px;
  }}
</style>
</head>
<body>
  <div class="name">{family}</div>
  <div class="members">{members_label}</div>
</body>
</html>"""
