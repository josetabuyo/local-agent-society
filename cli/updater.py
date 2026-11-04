#!/usr/bin/env python3
"""`las update` — pull, reinstall, and show what's new, oh-my-zsh style.

Stdlib only, runnable by path (`update.sh` execs it), so it works before
the venv is rebuilt and whatever Python is on PATH can run it.

Two phases, so the steps after the pull are always the NEW code:
  1. pull (this file as it was before the update),
  2. re-exec the freshly pulled copy of this file with `--after-pull OLD`,
     which runs stop → install → migrate → start → normalize quietly
     (spinner + ✓ per step, the full output in ~/.las/logs/update-*.log,
     any ⚠️ line surfaced under its step) and then prints the news between
     OLD and the new HEAD, grouped from the conventional-commit subjects.

`las changelog` reuses render_changelog() to show the news again.
"""
from __future__ import annotations

import itertools
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.getenv("LAS_UPDATE_LOG_DIR", str(Path.home() / ".las" / "logs")))
HEALTH_URL = "http://localhost:8700/health"

# ── colors ─────────────────────────────────────────────────────────────────

# Color and the spinner only on a live terminal. Claude Code's `! las update`
# shows output as plain text (raw escape codes were seen there, 2026-11-04,
# System@uy-mac), so CLAUDECODE means no color even on a tty. FORCE_COLOR /
# CLICOLOR_FORCE opt back in on purpose; NO_COLOR and TERM=dumb always win.
_LIVE = sys.stdout.isatty()


def _forced(var: str) -> bool:
    return os.getenv(var, "0") not in ("", "0")


_COLOR = ((_LIVE and not _forced("CLAUDECODE")) or _forced("FORCE_COLOR") or _forced("CLICOLOR_FORCE")) \
    and not os.getenv("NO_COLOR") and os.getenv("TERM") != "dumb"


def _sgr(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(t: str) -> str: return _sgr("1", t)
def dim(t: str) -> str: return _sgr("2", t)
def green(t: str) -> str: return _sgr("32", t)
def red(t: str) -> str: return _sgr("31", t)
def yellow(t: str) -> str: return _sgr("33", t)
def cyan(t: str) -> str: return _sgr("36", t)


# The widget's own palette, left to right: one 256-color code per column band.
_GRADIENT = [41, 42, 43, 44, 38, 32, 33, 69, 105, 141, 177, 213, 207, 205, 204, 209, 215, 221]

LOGO = [
    r" _                    _      _                    _     ____             _      _          ",
    r"| |    ___   ___ __ _| |    / \   __ _  ___ _ __ | |_  / ___|  ___   ___(_) ___| |_ _   _ ",
    r"| |   / _ \ / __/ _` | |   / _ \ / _` |/ _ \ '_ \| __| \___ \ / _ \ / __| |/ _ \ __| | | |",
    r"| |__| (_) | (_| (_| | |  / ___ \ (_| |  __/ | | | |_   ___) | (_) | (__| |  __/ |_| |_| |",
    r"|_____\___/ \___\__,_|_| /_/   \_\__, |\___|_| |_|\__| |____/ \___/ \___|_|\___|\__|\__, |",
    r"                                 |___/                                              |___/ ",
]

SMALL_LOGO = [
    r" _      _    ___ ",
    r"| |    /_\  / __|",
    r"| |__ / _ \ \__ \ ",
    r"|____/_/ \_\|___/",
]


def _gradient(line: str, width: int) -> str:
    if not _COLOR:
        return line
    out = []
    for i, ch in enumerate(line):
        if ch == " ":
            out.append(ch)
            continue
        code = _GRADIENT[min(len(_GRADIENT) - 1, i * len(_GRADIENT) // max(1, width))]
        out.append(f"\033[1;38;5;{code}m{ch}")
    return "".join(out) + "\033[0m"


def logo() -> str:
    cols = shutil.get_terminal_size((100, 24)).columns
    art = LOGO if cols >= max(len(l) for l in LOGO) + 2 else SMALL_LOGO
    width = max(len(l) for l in art)
    return "\n".join(_gradient(l, width) for l in art)


# ── git ────────────────────────────────────────────────────────────────────

def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False).stdout.strip()


def head() -> str:
    return git("rev-parse", "HEAD")


def version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M)
    return match.group(1) if match else "?"


# ── changelog ──────────────────────────────────────────────────────────────

# (type, title) in display order; anything else lands in "Maintenance".
SECTIONS = [
    ("feat", "✨ New"),
    ("fix", "🐛 Fixed"),
    ("perf", "⚡ Faster"),
    ("refactor", "♻️  Under the hood"),
    ("docs", "📚 Docs"),
]
MAINTENANCE = "🔧 Maintenance"
_SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<text>.+)$")
# Commits that are bookkeeping, not news.
_NOISE = re.compile(r"^docs: boarding test results", re.I)


def commits_between(old: str, new: str) -> list[dict]:
    raw = git("log", "--no-merges", "--reverse", "--format=%h%x1f%s%x1f%ad", "--date=short", f"{old}..{new}")
    out = []
    for line in filter(None, raw.splitlines()):
        sha, subject, date = (line.split("\x1f") + ["", ""])[:3]
        if _NOISE.match(subject):
            continue
        m = _SUBJECT.match(subject)
        out.append({
            "sha": sha,
            "date": date,
            "type": m.group("type") if m else "other",
            "scope": m.group("scope") if m else None,
            "breaking": bool(m and m.group("bang")),
            "text": m.group("text") if m else subject,
        })
    return out


def _wrap(text: str, indent: int, width: int) -> list[str]:
    room = max(30, width - indent)
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > room:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def render_changelog(commits: list[dict]) -> str:
    """The news, grouped by kind — every feat/fix in full, maintenance as a count."""
    if not commits:
        return ""
    width = min(100, shutil.get_terminal_size((100, 24)).columns)
    known = {t for t, _ in SECTIONS}
    groups: dict[str, list[dict]] = {}
    for c in commits:
        groups.setdefault(c["type"] if c["type"] in known else "_other", []).append(c)

    lines = []
    for key, title in SECTIONS + [("_other", MAINTENANCE)]:
        items = groups.get(key)
        if not items:
            continue
        lines.append("")
        lines.append(f"  {bold(title)} {dim(f'({len(items)})')}")
        for c in items:
            scope = f"{cyan(c['scope'])}: " if c["scope"] else ""
            brk = red("BREAKING ") if c["breaking"] else ""
            prefix_len = len(c["scope"]) + 2 if c["scope"] else 0
            body = _wrap(c["text"], 6 + prefix_len + 10, width)
            lines.append(f"    {yellow('•')} {brk}{scope}{body[0]}  {dim(c['sha'])}")
            for more in body[1:]:
                lines.append(f"      {' ' * prefix_len}{more}")
    return "\n".join(lines)


# ── steps ──────────────────────────────────────────────────────────────────

class Step:
    """One quiet step: a spinner while it runs, ✓/✗ and its time after; output to the log."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, title: str, log):
        self.title = title
        self.log = log

    def run(self, cmd: list[str], *, env: dict | None = None) -> bool:
        self.log.write(f"\n\n===== {self.title}: {' '.join(cmd)} =====\n")
        self.log.flush()
        start = time.time()
        proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env={**os.environ, **(env or {})}, stdin=subprocess.DEVNULL)
        warnings: list[str] = []
        done = threading.Event()
        spinner = threading.Thread(target=self._spin, args=(done, start), daemon=True)
        spinner.start()
        for line in proc.stdout:  # type: ignore[union-attr]
            self.log.write(line)
            if "⚠" in line:
                warnings.append(line.strip())
        proc.wait()
        done.set()
        spinner.join()
        self.finish(proc.returncode == 0, time.time() - start)
        for w in warnings:
            print(f"      {yellow(w)}")
        return proc.returncode == 0

    def _spin(self, done: threading.Event, start: float) -> None:
        if not (_LIVE and _COLOR):
            return
        for frame in itertools.cycle(self.FRAMES):
            if done.wait(0.08):
                break
            sys.stdout.write(f"\r  {cyan(frame)} {self.title} {dim(f'{time.time() - start:.0f}s')}\033[K")
            sys.stdout.flush()

    def finish(self, ok: bool, seconds: float | None = None) -> None:
        mark = green("✓") if ok else red("✗")
        took = f" {dim(f'{seconds:.1f}s')}" if seconds is not None else ""
        clear = "\r\033[K" if (_LIVE and _COLOR) else ""
        print(f"{clear}  {mark} {self.title}{took}", flush=True)


def _open_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"update-{datetime.now():%Y%m%d-%H%M%S}.log"
    return path, path.open("w")


def _fail(log_path: Path) -> int:
    print()
    print(red(f"  Update stopped. Last lines of {log_path}:"))
    for line in log_path.read_text(errors="replace").splitlines()[-15:]:
        print(dim(f"    {line}"))
    print()
    print(f"  Fix it, then run {bold('las update')} again.")
    return 1


def phase_pull(log_path: Path, log) -> int:
    print()
    print(f"  {bold('Updating Local Agent Society')} {dim(f'v{version()} · {head()[:7]}')}")
    print()
    old = head()
    # --no-rebase: a machine with local commits (a fix not pushed yet) merges
    # instead of stopping on "divergent branches"; a real conflict still stops.
    if not Step("Pulling the latest version", log).run(["git", "pull", "--no-rebase", "--no-edit"]):
        log.close()
        return _fail(log_path)
    log.close()
    # Hand over to the copy of this file that was just pulled.
    new_self = REPO / "cli" / "updater.py"
    sys.stdout.flush()  # exec drops anything still buffered (stdout is a pipe under `las update`)
    os.execv(sys.executable, [sys.executable, str(new_self), "--after-pull", old, "--log", str(log_path)])
    return 0  # not reached


def phase_install(old: str, log_path: Path) -> int:
    log = log_path.open("a")
    steps = [
        ("Stopping the society", ["bash", "stop.sh"]),
        # install.sh also pulls the vortexia sibling repo (a dependency).
        ("Installing dependencies (backend, bridge, vortexia)", ["bash", "install.sh"]),
    ]
    for title, cmd in steps:
        if not Step(title, log).run(cmd):
            log.close()
            return _fail(log_path)

    # Agent configs: .las-agent.json is the only name read (docs/adr/0001
    # addendum) — migrate any pre-rename .agent.json left on this machine.
    dev_root = REPO.parent
    legacy = subprocess.run(["find", str(dev_root), "-maxdepth", "5", "-name", ".agent.json", "-not", "-path", "*/node_modules/*", "-print", "-quit"],
                            capture_output=True, text=True).stdout.strip()
    if legacy:
        if not Step("Migrating legacy .agent.json files", log).run([sys.executable, "scripts/migrate-agent-json.py", str(dev_root)]):
            print(f"      {yellow('⚠️  migration failed — run scripts/migrate-agent-json.py by hand')}")

    if not Step("Starting backend and widget", log).run(["bash", "start.sh"]):
        log.close()
        return _fail(log_path)

    # Bring every agent's .las-agent.json to the canonical shape (fills what
    # is missing, never overwrites). Needs the backend, which start.sh brought up.
    for _ in range(10):
        try:
            urllib.request.urlopen(HEALTH_URL, timeout=1)
            break
        except Exception:
            time.sleep(1)
    las = shutil.which("las") or "las"
    if not Step("Normalizing agent configs", log).run([las, "agent", "normalize", "--all"]):
        print(f"      {yellow('⚠️  las agent normalize --all failed — run it by hand')}")
    log.close()

    new = head()
    commits = commits_between(old, new) if old != new else []
    print()
    if commits:
        print(f"  {bold('What’s new')} {dim(f'{old[:7]} → {new[:7]} · {len(commits)} change' + ('s' if len(commits) != 1 else ''))}")
        print(render_changelog(commits))
    else:
        print(f"  {green('Already on the latest version')} — nothing new since {old[:7]}.")
    print()
    print(logo())
    print()
    if commits:
        print(f"  {bold(green('Hooray!'))} Local Agent Society has been updated to {bold(f'v{version()}')} {dim(f'({new[:7]})')}.")
    else:
        print(f"  {bold(green('All good.'))} Local Agent Society is at {bold(f'v{version()}')} {dim(f'({new[:7]})')}.")
    print(f"  {dim('See the news again:')} las changelog   {dim('Full log:')} {dim(str(log_path))}")
    print()
    return 0


def main(argv: list[str]) -> int:
    if "--after-pull" in argv:
        old = argv[argv.index("--after-pull") + 1]
        log_path = Path(argv[argv.index("--log") + 1])
        return phase_install(old, log_path)
    log_path, log = _open_log()
    return phase_pull(log_path, log)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
