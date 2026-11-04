"""`las update` / `las changelog` news: conventional-commit subjects grouped into a changelog."""
from cli import updater


def _fake_log(monkeypatch, subjects):
    lines = "\n".join(f"abc{i:04d}\x1f{s}\x1f2026-11-04" for i, s in enumerate(subjects))
    monkeypatch.setattr(updater, "git", lambda *a: lines)


def test_commits_are_parsed_and_bookkeeping_is_dropped(monkeypatch):
    _fake_log(monkeypatch, [
        "feat(widget): ⌨ keyboard",
        "fix: a bubble can be dismissed",
        "refactor!: one case only",
        "docs: boarding test results — 330/330 passing",
        "Merge-less plain subject",
    ])
    commits = updater.commits_between("a", "b")
    assert [c["type"] for c in commits] == ["feat", "fix", "refactor", "other"]
    assert commits[0]["scope"] == "widget" and commits[0]["text"] == "⌨ keyboard"
    assert commits[2]["breaking"] is True
    assert commits[3]["text"] == "Merge-less plain subject"


def test_changelog_groups_in_order_with_counts(monkeypatch):
    monkeypatch.setattr(updater, "_COLOR", False)
    _fake_log(monkeypatch, ["fix: b", "feat(cli): a", "chore: c", "feat: d"])
    out = updater.render_changelog(updater.commits_between("a", "b"))
    assert out.index("✨ New (2)") < out.index("🐛 Fixed (1)") < out.index("🔧 Maintenance (1)")
    assert "cli: a" in out and "• d" in out
    assert "\033[" not in out, "no escape codes when color is off"


def test_empty_changelog_is_empty():
    assert updater.render_changelog([]) == ""


def test_long_subjects_wrap_inside_the_terminal():
    lines = updater._wrap("word " * 60, 20, 80)
    assert len(lines) > 1 and all(len(l) <= 60 for l in lines)


def test_color_follows_claude_code_and_force_vars_but_no_color_wins(monkeypatch):
    import importlib, sys as _sys
    def color_with(**env):
        for k in ("FORCE_COLOR", "CLICOLOR_FORCE", "CLAUDECODE", "NO_COLOR", "TERM"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr(_sys.stdout, "isatty", lambda: False)
        return importlib.reload(updater)._COLOR
    assert color_with() is False
    assert color_with(CLAUDECODE="1") is True
    assert color_with(FORCE_COLOR="1") is True
    assert color_with(CLAUDECODE="1", NO_COLOR="1") is False
    assert color_with(FORCE_COLOR="0") is False
    importlib.reload(updater)
