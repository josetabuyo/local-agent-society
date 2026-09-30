"""
Serialization tests for the TTS speak queue — backend/main.py's _drain_one()
and POST /queue/ack.

The queue exists so two agents never talk over each other. Playback happens
inside each agent's own widget process, so the drainer has to pace itself on
the widget's ack: publish one envelope, block until that clip is reported
done (or skipped), only then publish the next. These tests drive
_drain_one() directly — no background thread, no vortexia (_vortexia_publish
is captured) — and check that ordering, plus the two safety valves that keep
an absent or stalled widget from freezing everyone else's speech.

Regression for 2026-09-28: the drainer used to pop-and-publish as fast as it
could, so N agents reporting in the same second produced N overlapping
voices (four clips synthesized within 2s in session/widget.log).
"""
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class _NoStartThread(threading.Thread):
    """Import backend.main without its module-level drainer thread running."""

    def start(self):
        pass


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).parent.parent))
    if "backend.main" in sys.modules:
        del sys.modules["backend.main"]

    monkeypatch.setattr(threading, "Thread", _NoStartThread)
    import backend.main as main
    monkeypatch.undo()

    monkeypatch.setattr(main, "QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(main, "MUTED_FILE", tmp_path / "muted.json")
    # Short grace / no inter-clip gap so the "nobody claimed it" valve and the
    # happy path both run in well under a second.
    monkeypatch.setattr(main, "SPEAK_PICKUP_GRACE_S", 0.2)
    monkeypatch.setattr(main, "SPEAK_GAP_S", 0.0)

    published = []

    def capture_publish(topic, envelope, retain=False):
        published.append((topic, envelope))
        return True

    monkeypatch.setattr(main, "_vortexia_publish", capture_publish)
    main._published = published
    return main


@pytest.fixture
def client(app_module):
    return TestClient(app_module.app)


def _enqueue(client, name, text="Reporting: done."):
    resp = client.post("/queue/speak", json={"text": text, "voice": "Samantha", "name": name})
    assert resp.status_code == 200


def _drain_in_thread(app_module, times=1):
    def run():
        for _ in range(times):
            app_module._drain_one()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _wait_published(app_module, count, timeout=2.0):
    deadline = time.time() + timeout
    while len(app_module._published) < count and time.time() < deadline:
        time.sleep(0.01)
    assert len(app_module._published) >= count, (
        f"expected {count} published envelope(s), got {len(app_module._published)}"
    )
    return app_module._published[count - 1][1]


def _ack(client, speak_id, phase, reason=None):
    body = {"id": speak_id, "phase": phase}
    if reason:
        body["reason"] = reason
    return client.post("/queue/ack", json=body)


# ── the serialization itself ──────────────────────────────────────────────────

def test_speak_envelope_carries_an_id_and_drainer_waits_for_done(app_module, client):
    _enqueue(client, "A")
    t = _drain_in_thread(app_module)

    env = _wait_published(app_module, 1)
    assert app_module._published[0][0] == app_module.SPEAK_TOPIC
    assert env["kind"] == "speak" and env["to"] == "A" and env["voice"] == "Samantha"
    assert env["id"], "every speak envelope must carry an id the widget can ack"

    assert _ack(client, env["id"], "started").json() == {"ok": True, "known": True}
    time.sleep(app_module.SPEAK_PICKUP_GRACE_S + 0.2)
    assert t.is_alive(), "after 'started' the drainer must keep waiting for 'done', well past the pickup grace"

    assert _ack(client, env["id"], "done").json() == {"ok": True, "known": True}
    t.join(timeout=2)
    assert not t.is_alive(), "'done' must release the drainer"
    assert env["id"] not in app_module._speak_acks, "finished clips must not stay tracked"


def test_second_agent_is_not_published_until_first_reports_done(app_module, client):
    """The regression: two agents reporting at once must come out one after the other."""
    _enqueue(client, "A", "first agent's report")
    _enqueue(client, "B", "second agent's report")
    t = _drain_in_thread(app_module, times=2)

    first = _wait_published(app_module, 1)
    assert first["to"] == "A"
    _ack(client, first["id"], "started")
    time.sleep(app_module.SPEAK_PICKUP_GRACE_S + 0.3)
    assert len(app_module._published) == 1, "B was published while A was still playing — voices would overlap"

    _ack(client, first["id"], "done")
    second = _wait_published(app_module, 2)
    assert second["to"] == "B"
    assert second["id"] != first["id"]
    _ack(client, second["id"], "done")
    t.join(timeout=2)
    assert not t.is_alive()


def test_skipped_ack_releases_the_queue_immediately(app_module, client):
    """A muted (or voiceless, or failed) widget must free the speaker at once —
    not sit on the full per-clip timeout for a clip that never plays."""
    _enqueue(client, "Quiet", "x" * 2000)  # long text → long ceiling if it waited for 'done'
    t = _drain_in_thread(app_module)
    env = _wait_published(app_module, 1)
    _ack(client, env["id"], "started")
    _ack(client, env["id"], "skipped", reason="muted")
    t.join(timeout=1)
    assert not t.is_alive()


# ── safety valves ─────────────────────────────────────────────────────────────

def test_unclaimed_speak_is_dropped_after_the_pickup_grace(app_module, client):
    """No widget for that agent (closed, stale build, vortexia down): move on
    after the short grace instead of the long playback timeout."""
    _enqueue(client, "Ghost")
    started = time.time()
    assert app_module._drain_one() is True
    elapsed = time.time() - started
    assert app_module.SPEAK_PICKUP_GRACE_S <= elapsed < app_module.SPEAK_PICKUP_GRACE_S + 1.0
    assert app_module._speak_acks == {}


def test_stalled_widget_hits_the_per_clip_ceiling(app_module, client, monkeypatch):
    """Claimed but never reported done (widget died mid-clip): the ceiling fires."""
    monkeypatch.setattr(app_module, "SPEAK_SYNTH_HEADROOM_S", 0.2)
    monkeypatch.setattr(app_module, "SPEAK_MAX_WAIT_S", 0.3)
    _enqueue(client, "A")
    t = _drain_in_thread(app_module)
    env = _wait_published(app_module, 1)
    _ack(client, env["id"], "started")
    t.join(timeout=2)
    assert not t.is_alive(), "drainer must give up on a claimed clip once the ceiling passes"
    assert app_module._speak_acks == {}


def test_speak_timeout_scales_with_text_length_and_is_capped(app_module):
    short = app_module._speak_timeout_for("Reporting: done. X.")
    long = app_module._speak_timeout_for("x" * 5000)
    assert short < long
    assert long == app_module.SPEAK_MAX_WAIT_S
    assert short >= app_module.SPEAK_SYNTH_HEADROOM_S


def test_failed_publish_does_not_wait(app_module, client, monkeypatch):
    monkeypatch.setattr(app_module, "_vortexia_publish", lambda *a, **k: False)
    _enqueue(client, "A")
    started = time.time()
    assert app_module._drain_one() is True
    assert time.time() - started < app_module.SPEAK_PICKUP_GRACE_S
    assert app_module._speak_acks == {}


# ── filters that never reach vortexia ─────────────────────────────────────────

def test_muted_agent_is_dropped_without_publishing(app_module, client):
    app_module.save_json(app_module.MUTED_FILE, ["Quiet"])
    _enqueue(client, "Quiet")
    assert app_module._drain_one() is True
    assert app_module._published == []


def test_unknown_voice_is_dropped_without_publishing(app_module):
    app_module.save_json(app_module.QUEUE_FILE, [{"text": "hi", "voice": "TotallyMadeUpVoice", "name": "X"}])
    assert app_module._drain_one() is True
    assert app_module._published == []


def test_empty_queue_reports_idle(app_module):
    assert app_module._drain_one() is False


# ── POST /queue/ack contract ──────────────────────────────────────────────────

def test_ack_for_unknown_id_is_harmless(client):
    resp = client.post("/queue/ack", json={"id": "deadbeef", "phase": "done"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "known": False}


@pytest.mark.parametrize("body", [
    {"id": "x", "phase": "maybe"},
    {"id": "", "phase": "done"},
    {"phase": "done"},
])
def test_ack_validates_its_input(client, body):
    assert client.post("/queue/ack", json=body).status_code == 422
