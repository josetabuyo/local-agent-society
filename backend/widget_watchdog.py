"""Reopen the widget app when it crashes.

The backend runs under launchd (docs/adr/0002) and outlives the widget; the
widget does not. One SIGSEGV in Electron's main process (uy-mac, 2026-11-27:
an accessibility client asked AppKit for attributes of a freed window) took
every agent's widget down with it and nothing brought them back.

The widget writes `session/widget.running` (its pid) when it starts and
removes it on a clean quit (`las stop`, the app's own quit). So a marker whose
pid is no longer the widget means it died without quitting: reopen the app —
`open` on the bundle, the same thing `las start` does, so the single-instance
lock still rules out a second copy. At most MAX_RELAUNCHES per WINDOW_S: an
app that dies right on launch is not reopened in a loop.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from logging_config import logger

REPO = Path(__file__).resolve().parent.parent
MARKER = REPO / "session" / "widget.running"
APP_NAME = "Local Agent Society"
CHECK_S = 15
MAX_RELAUNCHES = 3
WINDOW_S = 600


def app_bundle(repo: Path = REPO) -> Path | None:
    for arch in ("mac-arm64", "mac"):
        p = repo / "widget-electron" / "dist" / arch / f"{APP_NAME}.app"
        if p.is_dir():
            return p
    return None


def widget_alive(pid: int) -> bool:
    """True when `pid` is still a running widget main process."""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return True  # can't tell: never relaunch on a guess
    return APP_NAME in out


def crashed_pid(marker: Path = MARKER, alive=widget_alive) -> int | None:
    """The pid of a widget that died without a clean quit, or None."""
    try:
        pid = int(marker.read_text().strip() or "0")
    except (OSError, ValueError):
        return None
    if pid <= 0 or alive(pid):
        return None
    return pid


class Watchdog:
    def __init__(self, marker: Path = MARKER, alive=widget_alive, launch=None, now=time.time):
        self.marker = marker
        self.alive = alive
        self.launch = launch or self._open_app
        self.now = now
        self.relaunches: list[float] = []

    @staticmethod
    def _open_app() -> bool:
        app = app_bundle()
        if not app:
            return False
        return subprocess.run(["open", str(app)], timeout=30).returncode == 0

    def check(self) -> str | None:
        """One pass: returns what was done ('relaunched' / 'gave-up'), or None."""
        pid = crashed_pid(self.marker, self.alive)
        if pid is None:
            return None
        t = self.now()
        self.relaunches = [x for x in self.relaunches if t - x < WINDOW_S]
        try:
            self.marker.unlink()  # the new instance writes its own
        except OSError:
            pass
        if len(self.relaunches) >= MAX_RELAUNCHES:
            logger.error(f"[widget-watchdog] the widget (pid {pid}) died again — {MAX_RELAUNCHES} reopenings in {WINDOW_S // 60} min, not reopening; run `las start`")
            return "gave-up"
        self.relaunches.append(t)
        ok = self.launch()
        logger.warning(f"[widget-watchdog] the widget (pid {pid}) died without quitting — {'reopened' if ok else 'could not reopen it'}")
        return "relaunched"


def start() -> None:
    if sys.platform != "darwin" or os.environ.get("LAS_NO_WIDGET_WATCHDOG"):
        return
    dog = Watchdog()

    def loop():
        while True:
            try:
                dog.check()
            except Exception as exc:
                logger.warning(f"[widget-watchdog] check failed: {exc}")
            time.sleep(CHECK_S)

    threading.Thread(target=loop, daemon=True, name="widget-watchdog").start()
