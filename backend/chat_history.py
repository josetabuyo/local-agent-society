"""Per-agent chat history: what each widget paints in its three bubble kinds,
kept by the backend so another surface (the phone app, through vortexia's
/device/* gateway) can show the same conversation.

Fed by a passive MQTT observer of every inbox and of `las/speak` (main.py):
it never consumes a mailbox, it only sees copies. An envelope lands in

  - its recipient's history: mic dictations (source human, from == to),
    messages from other agents, the agent's own speech (from "queue", kind
    "speak");
  - its sender's history when it goes to another agent (what this agent said
    to others).

Housekeeping (probes, self-tests, title requests, cc copies, scope queries)
never lands anywhere. Each agent keeps the last MAX_PER_AGENT messages, in
memory and in an append-only JSONL file per agent, compacted as it grows, so
a restart keeps the history.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import deque
from pathlib import Path

MAX_PER_AGENT = 500
_COMPACT_AT = MAX_PER_AGENT * 3
_SKIP_KINDS = {
    "probe", "mic-selftest", "mic-selftest-pong", "title-request", "cc",
    "scope-query", "scope-reply", "vortex-relay-direct-error",
}
_SKIP_PREFIXES = ("[las-channel-probe]", "[las-mic-selftest]", "[las-session-title]")
# Endpoints that are not agents: the device-audio system mailbox, the queue.
_NOT_AGENTS = {"las-device-audio", "queue", "broadcast"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._@-]+")


def _keep(envelope: dict) -> bool:
    if not isinstance(envelope, dict):
        return False
    text = envelope.get("text")
    if not isinstance(text, str) or not text.strip():
        return False
    if envelope.get("kind") in _SKIP_KINDS:
        return False
    return not text.lstrip().startswith(_SKIP_PREFIXES)


def _entry(envelope: dict, session: str | None) -> dict:
    # Some senders leave `id` out; a stable stand-in still deduplicates the
    # copies seen on the agent inbox and on a session inbox.
    eid = envelope.get("id") or envelope.get("msg_id")
    if not eid:
        digest = hashlib.sha1(envelope["text"].encode("utf-8")).hexdigest()[:10]
        eid = f"{envelope.get('from')}:{envelope.get('ts')}:{digest}"
    e = {
        "id": str(eid),
        "ts": int(envelope.get("ts") or 0),
        "from": envelope.get("from"),
        "to": envelope.get("to"),
        "text": envelope["text"],
        "kind": envelope.get("kind") or "message",
        "source": envelope.get("source") or "agent",
    }
    # Where a human input came from ("device:<env>" = dictated or typed on a
    # phone), so a surface can tell the phone's turns from the Mac's.
    if isinstance(envelope.get("via"), str) and envelope["via"]:
        e["via"] = envelope["via"]
    sess = envelope.get("session") or session
    if sess:
        e["session"] = sess
    return e


class ChatHistory:
    def __init__(self, directory: Path | None = None, max_per_agent: int = MAX_PER_AGENT):
        self.dir = Path(directory) if directory else None
        self.max = max_per_agent
        self._lock = threading.Lock()
        self._by_agent: dict[str, deque] = {}
        self._ids: dict[str, set] = {}
        self._lines: dict[str, int] = {}
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)

    def _file(self, agent: str) -> Path:
        return self.dir / f"{_SAFE_NAME.sub('_', agent)}.jsonl"

    def _load(self, agent: str) -> deque:
        if agent in self._by_agent:
            return self._by_agent[agent]
        q: deque = deque(maxlen=self.max)
        lines = 0
        if self.dir and self._file(agent).exists():
            for line in self._file(agent).read_text(encoding="utf-8").splitlines():
                lines += 1
                try:
                    q.append(json.loads(line))
                except ValueError:
                    continue
        self._by_agent[agent] = q
        self._ids[agent] = {e.get("id") for e in q if e.get("id")}
        self._lines[agent] = lines
        return q

    def _append(self, agent: str, entry: dict) -> None:
        q = self._load(agent)
        if entry["id"] and entry["id"] in self._ids[agent]:
            return
        if len(q) == q.maxlen and q[0].get("id"):
            self._ids[agent].discard(q[0]["id"])
        q.append(entry)
        if entry["id"]:
            self._ids[agent].add(entry["id"])
        if not self.dir:
            return
        f = self._file(agent)
        self._lines[agent] += 1
        if self._lines[agent] > _COMPACT_AT:
            tmp = f.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in q), encoding="utf-8")
            tmp.replace(f)
            self._lines[agent] = len(q)
        else:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record(self, envelope: dict, session: str | None = None) -> None:
        """One envelope seen on an inbox or on las/speak (deduplicated by id:
        the same message is seen on an agent inbox and on a session inbox)."""
        if not _keep(envelope):
            return
        entry = _entry(envelope, session)
        to, frm = entry["to"], entry["from"]
        with self._lock:
            if isinstance(to, str) and to and to not in _NOT_AGENTS:
                self._append(to, entry)
            if isinstance(frm, str) and frm and frm != to and frm not in _NOT_AGENTS and entry["kind"] != "speak":
                self._append(frm, entry)

    def query(self, agent: str, after: int | None = None, limit: int = 100) -> list[dict]:
        """Chronological; with `after` (a ts), only newer ones — the LAST
        `limit` of them, so a first call gets the most recent conversation."""
        with self._lock:
            q = list(self._load(agent))
        q.sort(key=lambda e: e.get("ts") or 0)
        if after is not None:
            q = [e for e in q if (e.get("ts") or 0) > after]
        return q[-limit:] if limit > 0 else []
