"""`las codex` runs the Codex TUI inside a PTY and types mailbox messages into it."""
import json
import os

from cli import pty_session


def test_mailbox_lines_are_pasted_into_the_tui_and_submitted_with_enter():
    inject_r, inject_w = os.pipe()
    stdin_r, stdin_w = os.pipe()
    out_r, out_w = os.pipe()
    # A stand-in TUI: read one line, echo it back tagged, exit 3.
    argv = ["/bin/sh", "-c", 'read -r line; printf "got:%s\\n" "$line"; exit 3']
    os.write(inject_w, (json.dumps({"from": "Vortexia", "source": "agent", "text": "port 9012 freed"}) + "\n").encode())
    os.close(inject_w)
    code = pty_session.run_in_pty(argv, inject_fd=inject_r, stdin_fd=stdin_r, stdout_fd=out_w)
    os.close(out_w)
    os.close(stdin_w)
    output = os.read(out_r, 65536).decode()
    assert code == 3, "the child's exit code comes back"
    assert "got:" in output and "[LAS message from Vortexia] port 9012 freed" in output
    assert "\x1b[200~" in output, "bracketed paste, so a multi-line message never submits early"


def test_human_keystrokes_are_forwarded_and_injection_names_the_mic():
    inject_r, inject_w = os.pipe()
    stdin_r, stdin_w = os.pipe()
    out_r, out_w = os.pipe()
    argv = ["/bin/sh", "-c", 'read -r a; read -r b; printf "a=%s|b=%s\\n" "$a" "$b"']
    os.write(stdin_w, b"typed by hand\r")
    os.close(stdin_w)
    os.write(inject_w, (json.dumps({"from": "Robo", "source": "human", "text": "dictated"}) + "\n").encode())
    os.close(inject_w)
    code = pty_session.run_in_pty(argv, inject_fd=inject_r, stdin_fd=stdin_r, stdout_fd=out_w)
    os.close(out_w)
    output = os.read(out_r, 65536).decode()
    assert code == 0
    assert "a=typed by hand" in output
    assert "b=" in output and "[LAS message from mic] dictated" in output


def test_format_injection_tags_agent_and_mic():
    assert pty_session.format_injection({"from": "Pulpo", "source": "agent", "text": "hi"}) == "[LAS message from Pulpo] hi"
    assert pty_session.format_injection({"from": "Me", "source": "human", "text": "hi"}) == "[LAS message from mic] hi"
