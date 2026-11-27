"""The backend reopens the widget app after a crash, never after a clean stop."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import widget_watchdog as wd  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def make(tmp_path, pid="4242", alive=False):
    marker = tmp_path / "widget.running"
    if pid is not None:
        marker.write_text(pid)
    launches = []
    clock = [1000.0]
    dog = wd.Watchdog(marker=marker, alive=lambda _p: alive, launch=lambda: launches.append(1) or True, now=lambda: clock[0])
    return dog, marker, launches, clock


def test_no_marker_means_a_clean_quit(tmp_path):
    dog, _, launches, _ = make(tmp_path, pid=None)
    assert dog.check() is None and launches == []


def test_a_live_widget_is_left_alone(tmp_path):
    dog, marker, launches, _ = make(tmp_path, alive=True)
    assert dog.check() is None and launches == [] and marker.exists()


def test_a_dead_pid_is_a_crash_and_reopens_once(tmp_path):
    dog, marker, launches, _ = make(tmp_path)
    assert dog.check() == "relaunched" and launches == [1]
    assert not marker.exists()          # the new instance writes its own
    assert dog.check() is None and launches == [1]


def test_a_crash_loop_is_not_reopened_forever(tmp_path):
    dog, marker, launches, clock = make(tmp_path)
    for _ in range(wd.MAX_RELAUNCHES):
        marker.write_text("4242")
        assert dog.check() == "relaunched"
    marker.write_text("4242")
    assert dog.check() == "gave-up" and len(launches) == wd.MAX_RELAUNCHES
    clock[0] += wd.WINDOW_S + 1          # later on, a new crash is reopened again
    marker.write_text("4242")
    assert dog.check() == "relaunched"


def test_the_widget_and_stop_keep_the_marker_contract():
    main = (REPO / "widget-electron" / "main.js").read_text()
    assert "widget.running" in main and "will-quit" in main and "app.isPackaged" in main
    stop = (REPO / "stop.sh").read_text()
    assert stop.index("session/widget.running") < stop.index("kill $PIDS")
    assert "_widget_watchdog.start()" in (REPO / "backend" / "main.py").read_text()
