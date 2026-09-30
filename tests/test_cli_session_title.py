"""`las agent title` finds the session it runs inside by process ancestry."""
from cli.commands import agents


def test_own_session_by_ancestry(monkeypatch):
    parents = {10: 5, 20: 7, 30: 5}
    monkeypatch.setattr(agents, "_parent_pid", lambda pid: parents.get(pid))
    claude = {"sid": "claude-10", "pid": 10}   # bridge started by Claude (pid 5)
    codex = {"sid": "codex-20", "pid": 20}     # bridge started by `las codex` (pid 7)
    shell = {"sid": "shell-40", "pid": 40}     # the bridge IS an ancestor of what it runs
    assert agents.own_session([claude, codex], {5, 3})["sid"] == "claude-10"
    assert agents.own_session([claude, codex], {7, 3})["sid"] == "codex-20"
    assert agents.own_session([claude, codex, shell], {40, 3})["sid"] == "shell-40"
    assert agents.own_session([claude, codex], {99}) is None
    twin = {"sid": "claude-30", "pid": 30}     # two bridges under one parent: ambiguous, ask for --session
    assert agents.own_session([claude, twin], {5}) is None
