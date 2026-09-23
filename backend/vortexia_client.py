"""
vortexia_client.py — thin Python client for the vortexia MQTT broker.

Vendored copy of vortexia's python/vortexia_client.py (sibling project at
../vortexia). Kept in sync by hand since the two repos aren't packaged
together. See /Users/josetabuyo/Development/vortexia/PROTOCOL.md for the
full protocol this implements.

Mirrors the JS client's API (register/send) and adds a poll-and-collect
helper for one-shot CLI invocations that can't stay subscribed forever.

Requires `paho-mqtt` — a real dependency of this backend now, see
backend/requirements.txt.

Topic schema (see PROTOCOL.md):
    las/agent/<name>/inbox      - direct message to one agent
    las/broadcast               - message to all agents
    las/agent/<name>/presence   - retained LWT presence ("online"/"offline")

Message envelope (JSON): {from, to, source, text, ts}
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "vortexia_client requires paho-mqtt. Install it with: pip install paho-mqtt"
    ) from exc


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 1883


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def resolve_mqtt_port(ports: Optional[dict] = None,
                      port_file_candidates: Optional[list] = None,
                      default: Optional[int] = DEFAULT_PORT) -> Optional[int]:
    """Resolve the broker's current TCP MQTT port, mirroring vortexia's own
    client.js precedence: vortexia.port.json -> port registry -> DEFAULT_PORT.

    Why the port file comes first: vortexia claims its ports from the :8700
    registry at startup, and falls back to 1883 when the registry isn't up
    yet. On a cold boot both services are launchd jobs racing each other, so
    the broker can easily end up on 1883 while the registry still holds a
    stale claim (9014) from the previous run — every backend/CLI publish then
    goes to a port nobody listens on and vortexia is "unreachable" even
    though it's running fine (seen 2026-09-23). vortexia.port.json is written
    by the live broker *after* it binds, with its pid, so it's the
    authoritative answer whenever that pid is still alive.

    `ports` is the registry's ports.json content; `port_file_candidates` is an
    ordered list of paths to try for vortexia.port.json. Both default to what
    this checkout can see (see default_port_file_candidates()). `default` is
    returned when neither source knows a broker — pass None to be told that
    instead of getting the 1883 guess (e.g. a command that must fail soft
    rather than block on a connect to a port nobody listens on).
    """
    ports = ports or {}
    if port_file_candidates is None:
        port_file_candidates = default_port_file_candidates(ports)
    for candidate in port_file_candidates:
        try:
            data = json.loads(Path(candidate).read_text())
        except (OSError, ValueError):
            continue
        port = data.get("mqttPort")
        pid = data.get("pid")
        if port and (pid is None or _pid_alive(pid)):
            return int(port)

    claims = [info for info in ports.values() if info.get("app") == "vortexia-mqtt"]
    if claims:
        # Claims accumulate rather than get cleaned up on restart — the most
        # recently registered one is the best guess among them.
        latest = max(claims, key=lambda info: info.get("registered_at", ""))
        if latest.get("port"):
            return int(latest["port"])
    return default


def default_port_file_candidates(ports: Optional[dict] = None) -> list:
    """Where a live vortexia's port.json might be, most specific first:
    $VORTEXIA_DIR, the path recorded on its registry claim, then the sibling
    checkout next to this repo (the layout install.sh creates)."""
    dirs = []
    env_dir = os.environ.get("VORTEXIA_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    for info in (ports or {}).values():
        if str(info.get("app", "")).startswith("vortexia") and info.get("path"):
            dirs.append(Path(info["path"]))
    dirs.append(Path(__file__).resolve().parents[2] / "vortexia")
    seen, out = set(), []
    for d in dirs:
        f = d / "vortexia.port.json"
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def inbox_topic(name: str) -> str:
    return f"las/agent/{name}/inbox"


def presence_topic(name: str) -> str:
    return f"las/agent/{name}/presence"


BROADCAST_TOPIC = "las/broadcast"


def build_envelope(from_: str, to: str, text: str, source: str = "agent") -> dict:
    return {
        "from": from_,
        "to": to,
        "source": source,
        "text": text,
        "ts": int(time.time() * 1000),
    }


class VortexiaClient:
    """
    A small paho-mqtt wrapper mirroring the JS VortexiaClient API.

    Usage:
        client = VortexiaClient(host="localhost", port=1883)
        client.register("MyAgent")
        client.send("OtherAgent", "hello")
        client.close()
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.name: Optional[str] = None
        self._client: Optional[mqtt.Client] = None
        self._on_message: Optional[Callable[[dict, str], None]] = None

    def register(self, name: str, on_message: Optional[Callable[[dict, str], None]] = None) -> "VortexiaClient":
        """Connect, set LWT presence, subscribe to own inbox + broadcast."""
        self.name = name
        self._on_message = on_message

        client_id = f"vortexia-{name}-{uuid.uuid4().hex[:8]}"
        client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        client.will_set(presence_topic(name), payload="offline", qos=1, retain=True)

        def _on_connect(c, userdata, flags, rc):
            c.publish(presence_topic(name), "online", qos=1, retain=True)
            c.subscribe([(inbox_topic(name), 1), (BROADCAST_TOPIC, 1)])

        def _on_message(c, userdata, msg):
            try:
                envelope = json.loads(msg.payload.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return
            if self._on_message:
                self._on_message(envelope, msg.topic)

        client.on_connect = _on_connect
        client.on_message = _on_message

        client.connect(self.host, self.port, keepalive=30)
        client.loop_start()
        self._client = client
        return self

    def send(self, to: str, text: str, from_: Optional[str] = None, source: str = "agent") -> dict:
        """Publish a direct message (or 'broadcast' to reach everyone).

        Direct inbox messages are published RETAINED — see the JS client's
        send() for the full rationale (plain MQTT delivery only reaches
        subscribers connected at that instant, which loses any message sent
        while nobody happened to be listening; poll_inbox below is what
        clears the retained flag once a message is actually consumed).
        Broadcast is not retained.
        """
        if not self._client:
            raise RuntimeError("client not registered — call register(name) first")
        envelope = build_envelope(from_ or self.name, to, text, source)
        is_broadcast = to == "broadcast"
        topic = BROADCAST_TOPIC if is_broadcast else inbox_topic(to)
        self._client.publish(topic, json.dumps(envelope), qos=1, retain=not is_broadcast)
        return envelope

    def close(self) -> None:
        if not self._client:
            return
        if self.name:
            self._client.publish(presence_topic(self.name), "offline", qos=1, retain=True)
            time.sleep(0.1)  # give the publish a moment to flush before disconnecting
        self._client.loop_stop()
        self._client.disconnect()
        self._client = None


def poll_inbox(name: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 2.0) -> list[dict]:
    """
    Connect just long enough to drain any pending/retained messages for
    `name`'s inbox, then disconnect. Useful for a CLI tool invoked fresh
    each time, which can't stay subscribed indefinitely.

    This is the "real" consumer of a retained inbox message (see
    VortexiaClient.send): once collected here, the retained flag on the
    inbox topic is cleared (an empty retained publish, the standard MQTT way
    to remove a retained message) so the SAME message isn't handed to every
    future poll forever. A live viewer subscribed via VortexiaClient.register
    (e.g. the Electron widget) does NOT do this — it only displays messages
    as they arrive, leaving the retained copy for this function to actually
    consume later.

    Returns a list of message envelopes received within `timeout` seconds.
    """
    collected: list[dict] = []

    client_id = f"vortexia-poll-{name}-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

    def _on_connect(c, userdata, flags, rc):
        c.subscribe(inbox_topic(name), qos=1)

    def _on_message(c, userdata, msg):
        try:
            collected.append(json.loads(msg.payload.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            pass

    client.on_connect = _on_connect
    client.on_message = _on_message

    client.connect(host, port, keepalive=int(timeout) + 5)
    client.loop_start()
    time.sleep(timeout)
    if collected:
        # Clear the retained message now that it's been read — an empty
        # retained publish is the standard MQTT idiom for "delete the
        # retained value on this topic".
        client.publish(inbox_topic(name), payload=None, qos=1, retain=True)
        time.sleep(0.1)  # let the clear publish flush before disconnecting
    client.loop_stop()
    client.disconnect()

    return collected
