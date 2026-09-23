"""Folder-derived agent hierarchy: cli/hierarchy.py, the backend endpoint,
and the CLI commands built on it (children / parent / send --children /
agents --tree).

Nothing declares a parent anywhere — the only input is each agent's
registered `path`, so every test builds a registry (or a tmp folder tree)
and asserts what falls out of it.
"""
import json
import sys
import threading as _threading
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.hierarchy import children_of, parent_of, roots, tree_lines
from cli.commands import agents as agents_mod


def reg(**paths):
    """Build a registry {name: {"path": ...}} from keyword args."""
    return {name: {"path": path, "voice": "Samantha"} for name, path in paths.items()}


# ── pure functions ─────────────────────────────────────────────────────────────

def test_parent_is_nearest_registered_ancestor():
    r = reg(Top="/w/top", Mid="/w/top/mid", Leaf="/w/top/mid/deep/leaf")
    assert parent_of("Leaf", r) == "Mid"       # not Top, even though Top also contains it
    assert parent_of("Mid", r) == "Top"
    assert parent_of("Top", r) is None


def test_parent_skips_unregistered_intermediate_folders():
    r = reg(Top="/w/top", Leaf="/w/top/not-an-agent/leaf")
    assert parent_of("Leaf", r) == "Top"


def test_sibling_prefix_is_not_containment():
    """/w/relay must not be mistaken for an ancestor of /w/relay-ros."""
    r = reg(Relay="/w/relay", RelayRos="/w/relay-ros")
    assert parent_of("RelayRos", r) is None
    assert children_of("Relay", r) == []


def test_children_direct_vs_deep():
    r = reg(Top="/w/top", A="/w/top/a", B="/w/top/b", A1="/w/top/a/one", Other="/w/other")
    assert children_of("Top", r) == ["A", "B"]
    assert children_of("Top", r, deep=True) == ["A", "A1", "B"]
    assert children_of("A", r) == ["A1"]
    assert children_of("Other", r) == []


def test_children_of_unknown_agent_is_empty():
    assert children_of("Nope", reg(Top="/w/top")) == []


def test_roots_and_tree():
    r = reg(Top="/w/top", A="/w/top/a", A1="/w/top/a/one", Solo="/w/solo")
    assert roots(r) == ["Solo", "Top"]
    lines = tree_lines(r)
    assert lines == ["Solo", "Top", "  └─ A", "    └─ A1"]
    assert tree_lines(r, root="A") == ["A", "  └─ A1"]


def test_tree_marker_suffix():
    r = reg(Top="/w/top", A="/w/top/a")
    r["A"]["inactive"] = True
    lines = tree_lines(r, marker=lambda n, i: " (off)" if i.get("inactive") else "")
    assert lines == ["Top", "  └─ A (off)"]


# ── backend endpoint ───────────────────────────────────────────────────────────

class _NoStartThread(_threading.Thread):
    def start(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    if "backend.main" in sys.modules:
        del sys.modules["backend.main"]
    monkeypatch.setattr(_threading, "Thread", _NoStartThread)
    import backend.main as main
    monkeypatch.undo()
    monkeypatch.setattr(main, "REGISTRY_FILE", tmp_path / "registry.json")
    monkeypatch.setattr(main, "INACTIVE_FILE", tmp_path / "inactive.json")
    monkeypatch.setattr(main, "WAKE_ENABLED_FILE", tmp_path / "wake.json")
    return TestClient(main.app)


def test_hierarchy_endpoint(client):
    for name, path in [("Top", "/w/top"), ("A", "/w/top/a"), ("A1", "/w/top/a/one"), ("Solo", "/w/solo")]:
        assert client.post("/agents", json={"name": name, "voice": "Paulina", "path": path}).status_code == 200

    top = client.get("/agents/Top/hierarchy").json()
    assert top["parent"] is None
    assert [c["name"] for c in top["children"]] == ["A"]
    assert top["children"][0]["voice"] == "Paulina"
    assert top["deep"] is False

    deep = client.get("/agents/Top/hierarchy", params={"deep": "true"}).json()
    assert [c["name"] for c in deep["children"]] == ["A", "A1"]

    assert client.get("/agents/A1/hierarchy").json()["parent"] == "A"
    assert client.get("/agents/Solo/hierarchy").json() ["children"] == []
    assert client.get("/agents/Ghost/hierarchy").status_code == 404


# ── CLI ────────────────────────────────────────────────────────────────────────

class FakeApi:
    """Records calls; `hierarchy` answers GET /agents/<n>/hierarchy."""

    def __init__(self, registry=None, hierarchy=None, injected=True):
        self.registry = registry or {}
        self.hierarchy = hierarchy or {}
        self.injected = injected
        self.posts = []

    def get(self, path):
        if path == "/agents":
            return self.registry
        if path.startswith("/agents/") and "/hierarchy" in path:
            name = path.split("/")[2]
            deep = path.endswith("deep=true")
            h = self.hierarchy.get(name, {"parent": None, "children": []})
            kids = h["children"]
            if not deep:
                kids = [c for c in kids if not c.get("_deep_only")]
            return {"name": name, "parent": h["parent"], "children": kids, "deep": deep}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, payload):
        self.posts.append((path, payload))
        return {"ok": True, "injected": self.injected, "mode": "local"}


@pytest.fixture
def fake_api(monkeypatch):
    def install(**kw):
        fake = FakeApi(**kw)
        monkeypatch.setattr(agents_mod, "api", fake)
        return fake
    return install


def test_children_command_lists_and_hints_deep(fake_api):
    fake_api(hierarchy={"Top": {"parent": None, "children": [
        {"name": "A", "path": "/w/top/a", "voice": "Paulina"},
        {"name": "A1", "path": "/w/top/a/one", "voice": "Paulina", "_deep_only": True},
    ]}})
    r = CliRunner().invoke(agents_mod.children, ["Top"])
    assert r.exit_code == 0, r.output
    assert "A " in r.output and "A1" not in r.output
    r = CliRunner().invoke(agents_mod.children, ["Top", "--deep"])
    assert "A1" in r.output
    r = CliRunner().invoke(agents_mod.children, ["Nobody"])
    assert "no subordinates" in r.output and "--deep" in r.output


def test_parent_command(fake_api):
    fake_api(hierarchy={"A": {"parent": "Top", "children": []}})
    assert CliRunner().invoke(agents_mod.parent, ["A"]).output.strip() == "Top"
    assert "top-level" in CliRunner().invoke(agents_mod.parent, ["Top"]).output


def test_send_children_fans_out_one_send_per_subordinate(fake_api):
    fake = fake_api(hierarchy={"Top": {"parent": None, "children": [
        {"name": "A", "path": "/w/top/a"}, {"name": "B", "path": "/w/top/b"},
    ]}})
    r = CliRunner().invoke(agents_mod.send, ["hello", "--to", "Top", "--children", "--from", "Top"])
    assert r.exit_code == 0, r.output
    assert [p["to"] for _, p in fake.posts] == ["A", "B"]
    assert all(path == "/agents/send" and p["from_agent"] == "Top" for path, p in fake.posts)
    assert "2/2 subordinates reached" in r.output


def test_send_children_reports_failures_nonzero(fake_api):
    fake_api(injected=False, hierarchy={"Top": {"parent": None, "children": [{"name": "A", "path": "/w/top/a"}]}})
    r = CliRunner().invoke(agents_mod.send, ["hello", "--to", "Top", "--children"])
    assert r.exit_code == 1
    assert "0/1 subordinates reached" in r.output


def test_send_children_without_to_is_usage_error(fake_api):
    fake_api()
    r = CliRunner().invoke(agents_mod.send, ["hello", "--scope", "x", "--children"])
    assert r.exit_code == 2
    assert "--children/--deep need --to" in r.output


def test_send_children_with_no_subordinates_sends_nothing(fake_api):
    fake = fake_api()
    r = CliRunner().invoke(agents_mod.send, ["hello", "--to", "Solo", "--children"])
    assert r.exit_code == 0
    assert fake.posts == []
    assert "no subordinates" in r.output


def test_agents_tree_flag(fake_api):
    fake_api(registry={
        "Top": {"path": "/w/top", "voice": "x"},
        "A": {"path": "/w/top/a", "voice": "x", "inactive": True},
    })
    r = CliRunner().invoke(agents_mod.agents_list, ["--tree"])
    assert r.exit_code == 0, r.output
    assert r.output.splitlines() == ["Top", "  └─ A  (inactive)"]
