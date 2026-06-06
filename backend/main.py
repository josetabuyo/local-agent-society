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
MUTED_FILE    = DATA_DIR / "muted.json"

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
            name  = msg.get("name", "")
            muted = load_json(MUTED_FILE, [])
            if name in muted:
                continue
            voice = msg.get("voice", "Samantha")
            text  = msg.get("text", "")
            if text:
                subprocess.run(["say", "-v", voice, text], check=False)
        else:
            time.sleep(0.4)


threading.Thread(target=tts_drainer, daemon=True).start()


# ── models ────────────────────────────────────────────────────────────────────

class AgentRegistration(BaseModel):
    name:          str
    voice:         str
    path:          str
    backend_url:   str
    frontend_url:  str
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
    text:   str
    voice:  str
    name:   str


class AttributionEntry(BaseModel):
    file:      str
    agent:     str
    name:      str
    timestamp: str
    project:   str


class InjectRequest(BaseModel):
    message:     str
    source:      str           = "voice"   # "voice" | "agent" | "external"
    from_agent:  Optional[str] = None


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
    registry[agent.name] = {
        **agent.model_dump(),
        "registered_at": datetime.now().isoformat(),
    }
    save_json(REGISTRY_FILE, registry)
    return {"ok": True, "name": agent.name}


@app.delete("/agents/{name}")
def unregister_agent(name: str):
    registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")
    del registry[name]
    save_json(REGISTRY_FILE, registry)
    return {"ok": True}


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
    ports = load_json(PORTS_FILE, {})
    registered = {int(k) for k in ports.keys()}
    for port in range(start, end):
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
    queue = load_json(QUEUE_FILE, [])
    queue.append({"text": req.text, "voice": req.voice, "name": req.name})
    save_json(QUEUE_FILE, queue)
    return {"ok": True, "queue_length": len(queue)}


@app.get("/queue")
def get_queue():
    return load_json(QUEUE_FILE, [])


@app.delete("/queue")
def clear_queue():
    save_json(QUEUE_FILE, [])
    return {"ok": True}


# ── agent inject ─────────────────────────────────────────────────────────────

def _find_claude_tty(agent_path: str) -> str | None:
    """Find the TTY of a claude process whose cwd is exactly agent_path or a subdir."""
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
        for pid in pids:
            if not pid.isdigit():
                continue
            lsof_out = subprocess.run(
                ["/usr/sbin/lsof", "-p", pid, "-a", "-d", "cwd"],
                capture_output=True, text=True, timeout=5
            ).stdout
            # Parse cwd from lsof output — avoid substring false matches
            for line in lsof_out.splitlines()[1:]:
                parts = line.split()
                if not parts:
                    continue
                cwd = parts[-1]
                if cwd == agent_path or cwd.startswith(agent_path + "/"):
                    tty = subprocess.run(
                        ["ps", "-p", pid, "-o", "tty="],
                        capture_output=True, text=True, timeout=5
                    ).stdout.strip()
                    if tty and tty != "??":
                        return tty
    except Exception:
        pass
    return None


def _inject_via_iterm(tty: str, message: str) -> dict:
    safe = (message
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\r", " ")
            .replace("\n", " "))
    tty_dev = tty if tty.startswith("/") else f"/dev/{tty}"
    delay_s = round(min(0.05 + len(safe) * 0.002, 1.0), 3)
    script = f'''
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
                            write text "{safe}" newline NO
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
'''
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
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
            "ts": ts,
            "delay_s": delay_s,
            "text_len": len(safe),
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
            "text_len": len(safe),
            "tty": tty_dev,
        }


@app.post("/agents/{name}/inject")
def inject_message(name: str, body: InjectRequest):
    registry = load_json(REGISTRY_FILE, {})
    if name not in registry:
        raise HTTPException(status_code=404, detail="Agent not found")

    path    = registry[name].get("path", "")
    message = body.message

    # Build context prefix so the agent always knows who's talking
    sender = body.from_agent
    if body.source == "raw":
        terminal_text = message
    elif body.source == "agent" and sender:
        terminal_text = f"[Message from {sender}]: {message}"
    elif body.source == "voice":
        terminal_text = f"[Widget Voice]: {message}"
    elif sender:
        terminal_text = f"[External: {sender}]: {message}"
    else:
        terminal_text = f"[External]: {message}"

    # Find the live claude session and inject directly into the terminal
    tty    = _find_claude_tty(path)
    result = _inject_via_iterm(tty, terminal_text) if tty else None
    injected = result["success"] if result else False

    # ── structured inject log ──────────────────────────────────────────────────
    log_path = Path(path) / "session" / "inject.log"
    if log_path.parent.exists():
        ts_full = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        preview = terminal_text[:60].replace("\n", " ") + ("…" if len(terminal_text) > 60 else "")
        if result:
            status = "OK" if result["success"] else f"FAIL(rc={result['returncode']})"
            log_line = (
                f"[{ts_full}] name={name} source={body.source} "
                f"tty={result['tty']} len={result['text_len']} "
                f"delay={result['delay_s']}s status={status} "
                f"stdout={result['stdout']!r} stderr={result['stderr']!r} "
                f"msg={preview!r}\n"
            )
        else:
            log_line = (
                f"[{ts_full}] name={name} source={body.source} "
                f"tty=not_found — no live session msg={preview!r}\n"
            )
        with open(log_path, "a") as f:
            f.write(log_line)

    return {"ok": True, "injected": injected, "tty": tty or "not found"}


# ── agent mute ────────────────────────────────────────────────────────────────

@app.post("/agents/{name}/mute")
def mute_agent(name: str):
    muted = load_json(MUTED_FILE, [])
    if name not in muted:
        muted.append(name)
        save_json(MUTED_FILE, muted)
    return {"ok": True, "muted": True, "name": name}


@app.delete("/agents/{name}/mute")
def unmute_agent(name: str):
    muted = load_json(MUTED_FILE, [])
    if name in muted:
        muted.remove(name)
        save_json(MUTED_FILE, muted)
    return {"ok": True, "muted": False, "name": name}


@app.get("/agents/{name}/muted")
def get_muted(name: str):
    muted = load_json(MUTED_FILE, [])
    return {"muted": name in muted, "name": name}


# ── attribution ───────────────────────────────────────────────────────────────

@app.post("/attribution")
def record_attribution(entry: AttributionEntry):
    log = load_json(ATTRIBUTION_FILE, [])
    log.append(entry.model_dump())
    save_json(ATTRIBUTION_FILE, log)
    return {"ok": True}


@app.get("/attribution")
def get_attribution(file: str = None, name: str = None):
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
