"""What each agent said aloud, as audio, for the phone app (it plays the
agent's own Kokoro voice instead of the phone's). The widget synthesizes
every speak as always, plays it, and also hands the clip (AAC m4a) here;
the phone fetches it through vortexia's GET-only /device/* proxy, whose
NIP-44 envelope caps a body at 65535 bytes — so a clip is served base64 in
parts of PART_BYTES raw bytes.

Kept small and short-lived: the last MAX_PER_AGENT clips per agent, for
MAX_AGE_S. Files live under <dir>/<agent>/<id>.m4a with a <id>.json beside.
"""
from __future__ import annotations

import base64
import json
import math
import re
import threading
import time
from pathlib import Path

MAX_PER_AGENT = 20
MAX_AGE_S = 3600
PART_BYTES = 40000
MAX_CLIP_BYTES = 8 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE = re.compile(r"[^A-Za-z0-9._@-]+")


class SpeechStore:
    def __init__(self, directory: Path, now=time.time):
        self.dir = Path(directory)
        self.now = now
        self._lock = threading.Lock()

    def _agent_dir(self, agent: str) -> Path:
        return self.dir / _SAFE.sub("_", agent)

    @staticmethod
    def valid_id(clip_id: str) -> bool:
        return bool(_ID.match(clip_id or ""))

    def _metas(self, agent: str) -> list[dict]:
        d = self._agent_dir(agent)
        if not d.exists():
            return []
        out = []
        for f in d.glob("*.json"):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (d / f"{f.stem}.m4a").exists():
                out.append(meta)
        return sorted(out, key=lambda m: m.get("ts") or 0)

    def _prune(self, agent: str) -> None:
        d = self._agent_dir(agent)
        metas = self._metas(agent)
        # Age counts from arrival here, not from the speak's own ts (a clock
        # on another process, possibly behind).
        cutoff = self.now() - MAX_AGE_S
        drop = [m for m in metas if (m.get("storedAt") or 0) < cutoff]
        keep = [m for m in metas if m not in drop]
        drop += keep[:-MAX_PER_AGENT] if len(keep) > MAX_PER_AGENT else []
        for m in drop:
            for ext in ("m4a", "json"):
                (d / f"{m['id']}.{ext}").unlink(missing_ok=True)

    def put(self, agent: str, clip_id: str, audio: bytes, *, ts: int, text: str, duration_ms: int | None, mime: str = "audio/mp4") -> dict:
        if not self.valid_id(clip_id):
            raise ValueError("bad id")
        if not audio or len(audio) > MAX_CLIP_BYTES:
            raise ValueError("empty or too large")
        meta = {"agent": agent, "id": clip_id, "ts": int(ts), "text": text, "durationMs": duration_ms, "mime": mime,
                "bytes": len(audio), "parts": max(1, math.ceil(len(audio) / PART_BYTES)), "storedAt": self.now()}
        with self._lock:
            d = self._agent_dir(agent)
            d.mkdir(parents=True, exist_ok=True)
            for ext, data in (("m4a", audio), ("json", json.dumps(meta, ensure_ascii=False).encode("utf-8"))):
                tmp = d / f".{clip_id}.{ext}.tmp"
                tmp.write_bytes(data)
                tmp.replace(d / f"{clip_id}.{ext}")
            self._prune(agent)
        return meta

    def list(self, agent: str, after: int | None = None) -> list[dict]:
        with self._lock:
            self._prune(agent)
            metas = self._metas(agent)
        if after is not None:
            metas = [m for m in metas if (m.get("ts") or 0) > after]
        return [{k: m.get(k) for k in ("id", "ts", "text", "durationMs", "mime", "parts")} for m in metas]

    def list_all(self, agents, after: int | None = None) -> list[dict]:
        """Every agent's recent clips in one chronological list (`agents`: the
        registry's names, so a stale folder is never listed)."""
        items = []
        for agent in agents:
            items += [{"agent": agent, **m} for m in self.list(agent, after=after)]
        return sorted(items, key=lambda m: m.get("ts") or 0)

    def part(self, agent: str, clip_id: str, part: int) -> dict | None:
        if not self.valid_id(clip_id):
            return None
        f = self._agent_dir(agent) / f"{clip_id}.m4a"
        try:
            data = f.read_bytes()
        except OSError:
            return None
        parts = max(1, math.ceil(len(data) / PART_BYTES))
        if part < 0 or part >= parts:
            return None
        chunk = data[part * PART_BYTES:(part + 1) * PART_BYTES]
        return {"id": clip_id, "part": part, "parts": parts, "b64": base64.b64encode(chunk).decode("ascii")}
