"""Shared filesystem helpers — no heavy dependencies."""
from __future__ import annotations

from collections import deque
from pathlib import Path

# Canonical agent-config filename. ".agent.json" is the pre-rename name kept
# only as a read fallback for agents not yet migrated (see
# scripts/migrate-agent-json.py) — every new write uses AGENT_CONFIG_FILENAME.
AGENT_CONFIG_FILENAME = ".las-agent.json"
LEGACY_AGENT_CONFIG_FILENAME = ".agent.json"
AGENT_CONFIG_FILENAMES = (AGENT_CONFIG_FILENAME, LEGACY_AGENT_CONFIG_FILENAME)


def agent_config_path(directory: str | Path) -> Path | None:
    """Return the agent-config file in `directory`, new name preferred, or None."""
    directory = Path(directory)
    for filename in AGENT_CONFIG_FILENAMES:
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def _has_agent_config(directory: Path) -> bool:
    return any((directory / filename).exists() for filename in AGENT_CONFIG_FILENAMES)


def find_nearest_agent_dir(cwd: str | Path, max_depth: int = 5) -> str | None:
    """Return the directory containing the nearest agent config, searching up then down (BFS).

    Strategy:
    1. Walk up from cwd — return the first ancestor that has an agent config.
    2. If nothing found going up, BFS downward up to max_depth levels.
    3. Return None if nothing found in either direction.
    """
    start = Path(cwd)
    for directory in [start, *start.parents]:
        if _has_agent_config(directory):
            return str(directory)
    queue: deque = deque([(start, 0)])
    while queue:
        directory, depth = queue.popleft()
        if depth > max_depth:
            break
        if _has_agent_config(directory):
            return str(directory)
        try:
            for d in sorted(d for d in directory.iterdir() if d.is_dir() and not d.name.startswith(".")):
                queue.append((d, depth + 1))
        except PermissionError:
            pass
    return None
