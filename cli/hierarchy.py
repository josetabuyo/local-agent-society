"""Agent hierarchy derived from the filesystem — no declared parent field.

The folders already encode the hierarchy: an agent whose registered `path`
sits under another agent's `path` is that agent's subordinate. Nothing is
written to `.las-agent.json` to say so, so it can never go stale — move the
folder and the hierarchy moves with it.

"Direct child" means the nearest registered ancestor is the parent, so an
agent registered at `A/x/y` whose only registered ancestor is `A` is a
direct child of `A`, even though `x` itself is not an agent.

Pure functions, no backend dependency: callable from the CLI, the backend
(`GET /agents/{name}/hierarchy`) and tests alike.
"""
from __future__ import annotations

from pathlib import Path


def _agent_path(info: dict) -> Path | None:
    raw = info.get("path")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _is_under(child: Path, ancestor: Path) -> bool:
    """True when `child` is strictly inside `ancestor` (not equal)."""
    if child == ancestor:
        return False
    try:
        child.relative_to(ancestor)
        return True
    except ValueError:
        return False


def parent_of(name: str, registry: dict) -> str | None:
    """Return the name of the nearest registered ancestor of `name`, or None."""
    me = _agent_path(registry.get(name, {}))
    if me is None:
        return None
    best: tuple[int, str] | None = None
    for other, info in registry.items():
        if other == name:
            continue
        other_path = _agent_path(info)
        if other_path is None or not _is_under(me, other_path):
            continue
        depth = len(other_path.parts)
        if best is None or depth > best[0]:
            best = (depth, other)
    return best[1] if best else None


def children_of(name: str, registry: dict, *, deep: bool = False) -> list[str]:
    """Return the subordinates of `name`, sorted by path.

    Direct children by default (their nearest registered ancestor is `name`);
    with `deep=True`, every descendant regardless of depth.
    """
    me = _agent_path(registry.get(name, {}))
    if me is None:
        return []
    found: list[tuple[Path, str]] = []
    for other, info in registry.items():
        if other == name:
            continue
        other_path = _agent_path(info)
        if other_path is None or not _is_under(other_path, me):
            continue
        if deep or parent_of(other, registry) == name:
            found.append((other_path, other))
    return [n for _, n in sorted(found)]


def roots(registry: dict) -> list[str]:
    """Agents with no registered ancestor, sorted by path."""
    top = [
        (_agent_path(info) or Path("/"), n)
        for n, info in registry.items()
        if parent_of(n, registry) is None
    ]
    return [n for _, n in sorted(top)]


def tree_lines(registry: dict, *, root: str | None = None, marker=lambda name, info: "") -> list[str]:
    """Render the hierarchy as indented lines (one per agent).

    `marker(name, info)` may return a suffix (e.g. " (inactive)") per line.
    With `root`, only that agent's subtree is rendered.
    """
    lines: list[str] = []

    def walk(name: str, depth: int) -> None:
        prefix = "  " * depth + ("└─ " if depth else "")
        lines.append(f"{prefix}{name}{marker(name, registry.get(name, {}))}")
        for child in children_of(name, registry):
            walk(child, depth + 1)

    for top in ([root] if root else roots(registry)):
        walk(top, 0)
    return lines
