"""Shared filesystem helpers — no heavy dependencies."""
from __future__ import annotations

from collections import deque
from pathlib import Path

# The one agent-config filename. The pre-rename ".agent.json" is no longer
# read anywhere: a machine that still has one runs
# scripts/migrate-agent-json.py once.
AGENT_CONFIG_FILENAME = ".las-agent.json"


def agent_config_path(directory: str | Path) -> Path | None:
    """Return the agent-config file in `directory`, or None."""
    candidate = Path(directory) / AGENT_CONFIG_FILENAME
    return candidate if candidate.exists() else None


def _has_agent_config(directory: Path) -> bool:
    return (directory / AGENT_CONFIG_FILENAME).exists()


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
