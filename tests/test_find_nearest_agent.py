"""Tests for find_nearest_agent_dir: up-then-down .agent.json search."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.path_utils import find_nearest_agent_dir as _find_nearest_agent_dir


def write_agent(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".agent.json").write_text(json.dumps({"name": name}))
    return directory


# ── walk-up cases ─────────────────────────────────────────────────────────────

def test_finds_in_exact_dir(tmp_path):
    write_agent(tmp_path, "Alpha")
    assert _find_nearest_agent_dir(str(tmp_path)) == str(tmp_path)


def test_walks_up_one_level(tmp_path):
    write_agent(tmp_path, "Alpha")
    subdir = tmp_path / "src"
    subdir.mkdir()
    assert _find_nearest_agent_dir(str(subdir)) == str(tmp_path)


def test_walks_up_multiple_levels(tmp_path):
    write_agent(tmp_path, "Alpha")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert _find_nearest_agent_dir(str(deep)) == str(tmp_path)


# ── walk-down cases ───────────────────────────────────────────────────────────

def test_walks_down_when_nothing_above(tmp_path):
    child = tmp_path / "project"
    write_agent(child, "Beta")
    assert _find_nearest_agent_dir(str(tmp_path)) == str(child)


def test_takes_shallowest_when_walking_down(tmp_path):
    shallow = tmp_path / "a"
    write_agent(shallow, "Shallow")
    deep = tmp_path / "b" / "c"
    write_agent(deep, "Deep")
    assert _find_nearest_agent_dir(str(tmp_path)) == str(shallow)


def test_up_wins_over_down(tmp_path):
    write_agent(tmp_path, "Parent")
    child = tmp_path / "sub"
    write_agent(child, "Child")
    # starting from tmp_path: up finds it immediately (current dir check)
    assert _find_nearest_agent_dir(str(tmp_path)) == str(tmp_path)


# ── edge cases ────────────────────────────────────────────────────────────────

def test_returns_none_when_nothing_found(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _find_nearest_agent_dir(str(empty)) is None
