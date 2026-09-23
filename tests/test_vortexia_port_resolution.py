"""
resolve_mqtt_port — where the backend and `las agent listen` look for the
vortexia broker. Regression for the 2026-09-23 reboot race: vortexia came up
before the :8700 registry, fell back to 1883, and the registry kept a stale
9014 claim, so everything published into the void while the broker was fine.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import vortexia_client as vx  # noqa: E402


def _port_file(tmp_path, **data):
    f = tmp_path / "vortexia.port.json"
    f.write_text(json.dumps(data))
    return f


STALE_REGISTRY = {
    "9014": {"port": 9014, "app": "vortexia-mqtt", "local_agent": "vortexia",
             "path": "/nonexistent/vortexia", "registered_at": "2026-09-17T10:14:21"},
}


def test_live_port_file_beats_stale_registry(tmp_path):
    f = _port_file(tmp_path, mqttPort=1883, wsPort=8883, pid=os.getpid())
    assert vx.resolve_mqtt_port(STALE_REGISTRY, [f]) == 1883


def test_port_file_with_dead_pid_is_ignored(tmp_path):
    # PID 2**22-1 is far above macOS/Linux pid_max in practice → not alive.
    f = _port_file(tmp_path, mqttPort=1883, pid=4194303)
    assert vx.resolve_mqtt_port(STALE_REGISTRY, [f]) == 9014


def test_registry_picks_latest_claim(tmp_path):
    ports = dict(STALE_REGISTRY)
    ports["9020"] = {"port": 9020, "app": "vortexia-mqtt", "local_agent": "vortexia",
                     "path": str(tmp_path), "registered_at": "2026-09-23T13:00:00"}
    assert vx.resolve_mqtt_port(ports, [tmp_path / "missing.json"]) == 9020


def test_default_when_nothing_known(tmp_path):
    assert vx.resolve_mqtt_port({}, [tmp_path / "missing.json"]) == vx.DEFAULT_PORT


def test_malformed_port_file_falls_through(tmp_path):
    f = tmp_path / "vortexia.port.json"
    f.write_text("{not json")
    assert vx.resolve_mqtt_port(STALE_REGISTRY, [f]) == 9014


def test_default_candidates_follow_env_claim_and_sibling(tmp_path, monkeypatch):
    monkeypatch.setenv("VORTEXIA_DIR", str(tmp_path / "env"))
    ports = {"9014": {"app": "vortexia-mqtt", "path": str(tmp_path / "claim")}}
    cands = vx.default_port_file_candidates(ports)
    assert cands[0] == tmp_path / "env" / "vortexia.port.json"
    assert cands[1] == tmp_path / "claim" / "vortexia.port.json"
    assert cands[-1].parent.name == "vortexia"  # sibling checkout, last resort


def test_default_none_reports_nothing_known(tmp_path):
    assert vx.resolve_mqtt_port({}, [tmp_path / "missing.json"], default=None) is None
