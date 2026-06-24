"""Shared filesystem helpers — no heavy dependencies."""
from __future__ import annotations

from collections import deque
from pathlib import Path


def find_nearest_agent_dir(cwd: str | Path, max_depth: int = 5) -> str | None:
    """Return the directory containing the nearest .agent.json, searching up then down (BFS).

    Strategy:
    1. Walk up from cwd — return the first ancestor that has .agent.json.
    2. If nothing found going up, BFS downward up to max_depth levels.
    3. Return None if nothing found in either direction.
    """
    start = Path(cwd)
    for directory in [start, *start.parents]:
        if (directory / ".agent.json").exists():
            return str(directory)
    queue: deque = deque([(start, 0)])
    while queue:
        directory, depth = queue.popleft()
        if depth > max_depth:
            break
        if (directory / ".agent.json").exists():
            return str(directory)
        try:
            for d in sorted(d for d in directory.iterdir() if d.is_dir() and not d.name.startswith(".")):
                queue.append((d, depth + 1))
        except PermissionError:
            pass
    return None
