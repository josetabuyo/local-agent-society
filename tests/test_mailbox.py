"""Mailbox migration (vortexia PROTOCOL.md "Mailboxes"): the LAS side of the
broker-owned persistent session per agent.

Three touchpoints, all covered here with a fake paho client — no broker:
  (a) backend inbox publishes are plain QoS 1, never retained
      (tests/test_api_endpoints.py asserts that on /inject);
  (b) poll_inbox connects as the mailbox consumer and stands down when a
      live listener already holds the session;
  (c) `las agent listen` is that consumer: fixed client id, persistent
      session, subscribes only when no session is present, never clears a
      retained slot, and exits instead of reconnecting when kicked.
"""
import json
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from cli.commands import agents as agents_mod


class FakeMQTTClient:
    instances: list = []

    def __init__(self, client_id=None, clean_session=True, protocol=None, **_):
        self.client_id = client_id
        self.clean_session = clean_session
        self.on_connect = self.on_message = self.on_disconnect = None
        self.subscribed, self.published, self.will = [], [], None
        self.session_present = False
        FakeMQTTClient.instances.append(self)

    def will_set(self, topic, payload=None, qos=0, retain=False):
        self.will = (topic, payload, retain)

    def subscribe(self, *a, **k):
        self.subscribed.append(a[0])

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append({"topic": topic, "payload": payload, "retain": retain})

    def connect(self, *a, **k):
        # paho 2.x on_connect signature: (client, userdata, flags, rc, properties)
        if self.on_connect:
            self.on_connect(self, None, {"session present": int(self.session_present)}, 0)

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def loop_forever(self):
        pass


@pytest.fixture
def fake_paho(monkeypatch):
    FakeMQTTClient.instances = []
    mod = types.SimpleNamespace(Client=FakeMQTTClient, MQTTv311="MQTTv311")
    pkg = types.ModuleType("paho.mqtt"); pkg.client = mod
    root = types.ModuleType("paho"); root.mqtt = pkg
    monkeypatch.setitem(sys.modules, "paho", root)
    monkeypatch.setitem(sys.modules, "paho.mqtt", pkg)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", mod)
    monkeypatch.delitem(sys.modules, "vortexia_client", raising=False)
    import vortexia_client as vx
    monkeypatch.setattr(vx, "mqtt", mod)
    monkeypatch.setattr(vx.time, "sleep", lambda *_: None)
    return vx


# ── (b) vendored client: poll_inbox / register ────────────────────────────────

def test_poll_inbox_connects_as_mailbox_consumer_without_touching_presence(fake_paho, monkeypatch):
    vx = fake_paho
    monkeypatch.setattr(vx, "session_state", lambda name, **k: {"connected": False})
    vx.poll_inbox("Ana", port=1)
    c = FakeMQTTClient.instances[-1]
    assert c.client_id == "las-agent-Ana"
    assert c.clean_session is False
    assert (vx.inbox_topic("Ana"), 1) in c.subscribed[0]      # fresh session: subscribes the inbox
    assert c.will is None                                       # no LWT
    assert all(p["topic"] != vx.presence_topic("Ana") for p in c.published)  # no online/offline flip
    assert not [p for p in c.published if p["retain"]]          # no retained clear-publish


def test_poll_inbox_does_not_resubscribe_when_session_present(fake_paho, monkeypatch):
    vx = fake_paho
    monkeypatch.setattr(vx, "session_state", lambda name, **k: {"connected": False})
    orig_init = FakeMQTTClient.__init__

    def init_with_session(self, *a, **k):
        orig_init(self, *a, **k)
        self.session_present = True

    monkeypatch.setattr(FakeMQTTClient, "__init__", init_with_session)
    vx.poll_inbox("Ana", port=1)
    subs = FakeMQTTClient.instances[-1].subscribed[0]
    assert (vx.inbox_topic("Ana"), 1) not in subs
    assert (vx.BROADCAST_TOPIC, 0) in subs


def test_poll_inbox_stands_down_when_listener_holds_the_session(fake_paho, monkeypatch):
    vx = fake_paho
    monkeypatch.setattr(vx, "session_state", lambda name, **k: {"connected": True, "clientId": "las-agent-Ana"})
    assert vx.poll_inbox("Ana", port=1) == []
    assert FakeMQTTClient.instances == []       # never connected as the mailbox


def test_poll_inbox_takeover_flag_ignores_live_listener(fake_paho, monkeypatch):
    vx = fake_paho
    monkeypatch.setattr(vx, "session_state", lambda name, **k: {"connected": True})
    vx.poll_inbox("Ana", port=1, takeover=True)
    assert FakeMQTTClient.instances[-1].client_id == "las-agent-Ana"


def test_register_default_still_manages_presence(fake_paho):
    vx = fake_paho
    client = vx.VortexiaClient(port=1).register("Ana")
    c = FakeMQTTClient.instances[-1]
    assert c.will == (vx.presence_topic("Ana"), "offline", True)
    assert {"topic": vx.presence_topic("Ana"), "payload": "online", "retain": True} in c.published
    assert c.clean_session is True and c.client_id.startswith("vortexia-Ana-")
    client.close()
    assert c.published[-1]["payload"] == "offline"


# ── (c) las agent listen ──────────────────────────────────────────────────────

@pytest.fixture
def listen_env(fake_paho, monkeypatch):
    monkeypatch.setattr(agents_mod.api, "get", lambda path: {"9012": {"app": "vortexia-mqtt", "port": 9012, "registered_at": "x"}} if path == "/ports" else {})
    monkeypatch.setattr(agents_mod.api, "post", lambda *a, **k: None)
    return fake_paho


def test_listen_is_the_mailbox_consumer(listen_env):
    vx = listen_env
    r = CliRunner().invoke(agents_mod.listen, ["Ana"])
    assert r.exit_code == 0, r.output
    c = FakeMQTTClient.instances[-1]
    assert c.client_id == "las-agent-Ana"
    assert c.clean_session is False
    assert c.subscribed == [vx.inbox_topic("Ana")]   # fresh session → subscribe once


def test_listen_skips_subscribe_when_broker_restored_the_session(listen_env, monkeypatch):
    orig_init = FakeMQTTClient.__init__

    def init_with_session(self, *a, **k):
        orig_init(self, *a, **k)
        self.session_present = True

    monkeypatch.setattr(FakeMQTTClient, "__init__", init_with_session)
    r = CliRunner().invoke(agents_mod.listen, ["Ana"])
    assert r.exit_code == 0, r.output
    assert FakeMQTTClient.instances[-1].subscribed == []


def test_listen_prints_message_and_never_clears_a_retained_slot(listen_env, monkeypatch):
    vx = listen_env

    def loop_forever(self):
        msg = types.SimpleNamespace(topic=vx.inbox_topic("Ana"),
                                    payload=json.dumps({"from": "Bo", "to": "Ana", "text": "hola"}).encode())
        self.on_message(self, None, msg)

    monkeypatch.setattr(FakeMQTTClient, "loop_forever", loop_forever)
    r = CliRunner().invoke(agents_mod.listen, ["Ana"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output.strip())["text"] == "hola"
    assert FakeMQTTClient.instances[-1].published == []   # no empty retained publish, no pong


def test_listen_exits_instead_of_reconnecting_when_session_is_taken_over(listen_env, monkeypatch):
    exits = []
    monkeypatch.setattr(agents_mod.os, "_exit", lambda code: exits.append(code))

    def loop_forever(self):
        self.on_disconnect(self, None, 7)   # unexpected drop: takeover or broker restart

    monkeypatch.setattr(FakeMQTTClient, "loop_forever", loop_forever)
    r = CliRunner().invoke(agents_mod.listen, ["Ana"])
    assert exits == [2]
    assert "mailbox session lost" in r.output


def test_listen_clean_disconnect_does_not_exit(listen_env, monkeypatch):
    exits = []
    monkeypatch.setattr(agents_mod.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(FakeMQTTClient, "loop_forever", lambda self: self.on_disconnect(self, None, 0))
    CliRunner().invoke(agents_mod.listen, ["Ana"])
    assert exits == []
