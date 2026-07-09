"""
Tests for the top-level CLI command groups (system/status, ports, voices,
queue) using click.testing.CliRunner.

`cli.api`'s get/post/delete/patch are monkeypatched to canned in-memory
responses -- no live backend is ever contacted. Each command group gets:

  - a happy-path test asserting the expected output is rendered from a
    canned response,
  - a backend-down test where the relevant cli.api function is monkeypatched
    to raise SystemExit(1) (mirroring cli.api._request's real behavior on a
    connection failure), asserting a clean non-zero exit with the error
    still visible in output,
  - (ports only) a malformed-response test for `las ports free` covering the
    guard in cli/commands/ports.py for responses missing the 'port' key.
"""
from click.testing import CliRunner

from cli.commands import system as system_mod
from cli.commands import ports as ports_mod
from cli.commands import voices as voices_mod
from cli.commands import queue as queue_mod


def _backend_down(*_a, **_kw):
    """Mimic cli.api._request's real behavior when the backend is unreachable."""
    print("Error: backend not running. Try `las start`.")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# las status
# ---------------------------------------------------------------------------

def test_status_happy_path(monkeypatch):
    responses = {
        "/health": {"status": "ok"},
        "/agents": {"agentA": {"voice": "Samantha", "path": "/tmp/agentA"}},
        "/ports": {"8700": {"local_agent": "backend"}},
    }
    monkeypatch.setattr(system_mod.api, "get", lambda path: responses[path])

    runner = CliRunner()
    result = runner.invoke(system_mod.status)

    assert result.exit_code == 0
    assert "Backend  : ok" in result.output
    assert "agentA" in result.output
    assert "Samantha" in result.output
    assert ":8700" in result.output
    assert "backend" in result.output


def test_status_backend_down(monkeypatch):
    monkeypatch.setattr(system_mod.api, "get", _backend_down)

    runner = CliRunner()
    result = runner.invoke(system_mod.status)

    assert result.exit_code != 0
    assert "backend not running" in result.output


# ---------------------------------------------------------------------------
# las ports ls
# ---------------------------------------------------------------------------

def test_ports_ls_happy_path(monkeypatch):
    data = {"8700": {"local_agent": "backend", "app": "api"}}
    monkeypatch.setattr(ports_mod.api, "get", lambda path: data)

    runner = CliRunner()
    result = runner.invoke(ports_mod.ports, ["ls"])

    assert result.exit_code == 0
    assert ":8700" in result.output
    assert "backend" in result.output
    assert "api" in result.output


def test_ports_ls_backend_down(monkeypatch):
    monkeypatch.setattr(ports_mod.api, "get", _backend_down)

    runner = CliRunner()
    result = runner.invoke(ports_mod.ports, ["ls"])

    assert result.exit_code != 0
    assert "backend not running" in result.output


# ---------------------------------------------------------------------------
# las ports free — malformed-response tolerance
# ---------------------------------------------------------------------------

def test_ports_free_malformed_response_missing_port_key(monkeypatch):
    """Backend returns a dict without 'port' -- must exit cleanly with an
    error, never print the literal string 'None' or raise KeyError."""
    monkeypatch.setattr(ports_mod.api, "get", lambda path: {"unexpected": "shape"})

    runner = CliRunner()
    result = runner.invoke(ports_mod.ports, ["free"])

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "None" not in result.output.split("\n")
    assert "Error" in result.output


def test_ports_free_happy_path(monkeypatch):
    monkeypatch.setattr(ports_mod.api, "get", lambda path: {"port": 9001})

    runner = CliRunner()
    result = runner.invoke(ports_mod.ports, ["free"])

    assert result.exit_code == 0
    assert result.output.strip() == "9001"


# ---------------------------------------------------------------------------
# las voices list
# ---------------------------------------------------------------------------

def test_voices_list_happy_path(monkeypatch):
    data = {"voices": [{"flag": "🇺🇸", "name": "Samantha", "lang": "en-US"}]}
    monkeypatch.setattr(voices_mod.api, "get", lambda path: data)

    runner = CliRunner()
    result = runner.invoke(voices_mod.voices, ["list"])

    assert result.exit_code == 0
    assert "Samantha" in result.output
    assert "en-US" in result.output


def test_voices_list_backend_down(monkeypatch):
    monkeypatch.setattr(voices_mod.api, "get", _backend_down)

    runner = CliRunner()
    result = runner.invoke(voices_mod.voices, ["list"])

    assert result.exit_code != 0
    assert "backend not running" in result.output


# ---------------------------------------------------------------------------
# las queue ls
# ---------------------------------------------------------------------------

def test_queue_ls_happy_path(monkeypatch):
    data = [{"name": "AgentA", "voice": "Samantha", "text": "hello"}]
    monkeypatch.setattr(queue_mod.api, "get", lambda path: data)

    runner = CliRunner()
    result = runner.invoke(queue_mod.queue, ["ls"])

    assert result.exit_code == 0
    assert "AgentA" in result.output
    assert "Samantha" in result.output
    assert "hello" in result.output


def test_queue_ls_empty(monkeypatch):
    monkeypatch.setattr(queue_mod.api, "get", lambda path: [])

    runner = CliRunner()
    result = runner.invoke(queue_mod.queue, ["ls"])

    assert result.exit_code == 0
    assert "Queue is empty." in result.output


def test_queue_ls_backend_down(monkeypatch):
    monkeypatch.setattr(queue_mod.api, "get", _backend_down)

    runner = CliRunner()
    result = runner.invoke(queue_mod.queue, ["ls"])

    assert result.exit_code != 0
    assert "backend not running" in result.output
