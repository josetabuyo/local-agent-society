"""The /las-agent skill is what every session loads at start, so it is
where the listener's noise is decided: how a session reacts to the
listener's Monitor expiring every 30 minutes, to it being killed, or to it
giving up. On 2026-09-23 a session that had done nothing but load the
skill produced a narrated paragraph plus a spoken "Reportando: listo"
on every expiry, and a 2m43s diagnosis on one exit 2 — noise that derails
the human's task and confuses the coding agents. These tests pin the
rules that keep that quiet, in the copy install.sh ships."""
from pathlib import Path

SKILL = (Path(__file__).parent.parent / ".claude/skills/las-agent/SKILL.md").read_text()


def _section(title: str) -> str:
    start = SKILL.index(title)
    end = SKILL.find("\n### ", start + 1)
    return SKILL[start:end if end != -1 else None]


def test_listener_housekeeping_turns_are_silent():
    live = _section("### Live listening")
    assert "Listener housekeeping is silent" in live
    assert "No closing report and no `las speak`" in live
    assert "No diagnosis, no `las agent poll`" in live
    # the three ways the listener ends on its own are all named as re-arm-and-hush
    for what in ("30 minutes", "exit 144", "exit 2"):
        assert what in live


def test_stall_and_sleep_drops_are_described_as_reconnects_not_fights():
    live = _section("### Live listening")
    assert "reconnected automatically" in live
    assert "die within seconds three times in a row" in live
    assert "kicked 3 times within a minute" not in live   # the old wall-clock rule is gone


def test_closing_report_is_skipped_on_housekeeping_turns():
    report = _section("### Closing report")
    assert "Not on housekeeping turns" in report
    assert "no closing report and no TTS at all" in report


def test_zombie_listener_is_purged_before_the_session_start_poll():
    presence = _section("### Presence registration and pending messages")
    purge = presence.index('pkill -f "las agent listen <agent_name>"')
    assert purge < presence.index("las agent register")
    assert purge < presence.index("las agent poll")


def test_monitor_snippet_matches_the_tool_that_exists():
    live = _section("### Live listening")
    assert "timeout_ms: 1800000" in live       # the Monitor tool caps a watch at 30 minutes
    assert "persistent: true" not in live      # no such option
