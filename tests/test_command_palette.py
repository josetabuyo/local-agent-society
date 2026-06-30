#!/usr/bin/env python3
"""
Guards for the command palette widget feature added in the 2026-06-30 session.

The terminal button now opens a command palette (CommandPaletteVC) instead of
immediately launching a terminal. Commands are stored as WidgetCommand values
in UserDefaults, grouped by kind (openTerminal / injectCommand), and shown with
monospace text and inline ▲▼✏ buttons.

All tests are static source-inspection — no running backend or compiled binary needed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PASS = 0
FAIL = 0


def ok(name: str):
    global PASS
    PASS += 1
    print(f"  PASS  {name}")


def fail(name: str, reason: str):
    global FAIL
    FAIL += 1
    print(f"  FAIL  {name}: {reason}")


def _swift_src() -> str:
    return (ROOT / "widget" / "tray.swift").read_text(encoding="utf-8")


def _extract_class(src: str, class_name: str) -> str:
    """Extract the body of a Swift class/struct by brace matching."""
    marker = f"class {class_name}"
    start = src.find(marker)
    if start == -1:
        marker = f"struct {class_name}"
        start = src.find(marker)
    if start == -1:
        return ""
    depth = 0
    for i, ch in enumerate(src[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start: i + 1]
    return ""


def _extract_func(src: str, func_name: str) -> str:
    """Extract a Swift function body by brace matching."""
    start = src.find(func_name)
    if start == -1:
        return ""
    depth = 0
    for i, ch in enumerate(src[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start: i + 1]
    return ""


# ── WidgetCommand struct ──────────────────────────────────────────────────────

def test_widget_command_struct_exists():
    """tray.swift must define struct WidgetCommand with openTerminal and injectCommand Kind cases."""
    src = _swift_src()
    wc = _extract_class(src, "WidgetCommand")
    if not wc:
        fail("WidgetCommand struct exists", "struct WidgetCommand not found in tray.swift")
        return
    if "openTerminal" in wc and "injectCommand" in wc:
        ok("struct WidgetCommand defines openTerminal and injectCommand Kind cases")
    else:
        fail("WidgetCommand Kind cases",
             "struct WidgetCommand must have Kind enum with openTerminal and injectCommand")


def test_widget_command_has_defaults():
    """WidgetCommand.defaults must include Haiku, Sonnet, Opus (openTerminal) and /clear (injectCommand)."""
    src = _swift_src()
    defaults_pos = src.find("static let defaults")
    if defaults_pos == -1:
        fail("WidgetCommand.defaults defined", "static let defaults not found in tray.swift")
        return
    block = src[defaults_pos: defaults_pos + 600]
    required = ["Haiku", "Sonnet", "Opus", "/clear"]
    missing = [r for r in required if r not in block]
    if not missing:
        ok("WidgetCommand.defaults contains Haiku, Sonnet, Opus, /clear")
    else:
        fail("WidgetCommand.defaults completeness",
             f"missing entries: {missing}")


# ── Prefs persistence ─────────────────────────────────────────────────────────

def test_prefs_has_widget_commands_methods():
    """Prefs must have widgetCommands(for:) and saveWidgetCommands(_:for:) using 'widgetCmds.' key prefix."""
    src = _swift_src()
    has_get = "widgetCommands(for:" in src
    has_save = "saveWidgetCommands(" in src
    has_key = '"widgetCmds.' in src
    if has_get and has_save and has_key:
        ok("Prefs has widgetCommands/saveWidgetCommands with 'widgetCmds.' UserDefaults key")
    else:
        missing = []
        if not has_get:  missing.append("widgetCommands(for:)")
        if not has_save: missing.append("saveWidgetCommands(_:for:)")
        if not has_key:  missing.append('"widgetCmds." key prefix')
        fail("Prefs widget commands persistence", f"missing: {', '.join(missing)}")


# ── CommandPaletteVC class ────────────────────────────────────────────────────

def test_command_palette_vc_exists():
    """tray.swift must define class CommandPaletteVC as the terminal-button popover controller."""
    src = _swift_src()
    if "class CommandPaletteVC" in src:
        ok("class CommandPaletteVC defined in tray.swift")
    else:
        fail("CommandPaletteVC exists", "class CommandPaletteVC not found in tray.swift")


def test_command_palette_shows_list():
    """CommandPaletteVC must have a showList() method that builds the command rows."""
    src = _extract_class(_swift_src(), "CommandPaletteVC")
    if not src:
        fail("CommandPaletteVC.showList exists", "CommandPaletteVC class not found")
        return
    if "func showList()" in src:
        ok("CommandPaletteVC has showList() method")
    else:
        fail("CommandPaletteVC.showList exists",
             "must have 'func showList()' to build the command list view")


def test_command_palette_shows_edit():
    """CommandPaletteVC must have a showEdit( method for inline add/edit of commands."""
    src = _extract_class(_swift_src(), "CommandPaletteVC")
    if not src:
        fail("CommandPaletteVC.showEdit exists", "CommandPaletteVC class not found")
        return
    if "func showEdit(" in src:
        ok("CommandPaletteVC has showEdit() method for inline editing")
    else:
        fail("CommandPaletteVC.showEdit exists",
             "must have 'func showEdit(' to support adding and editing commands")


# ── WidgetWindow integration ──────────────────────────────────────────────────

def test_command_palette_run_widget_command():
    """WidgetWindow must define func runWidgetCommand( to execute a WidgetCommand.
    CommandPaletteVC delegates execution here so it doesn't need direct access
    to private injectToSession / launchTerminal internals."""
    src = _swift_src()
    if "func runWidgetCommand(" in src:
        ok("WidgetWindow.runWidgetCommand( defined — palette delegates execution here")
    else:
        fail("WidgetWindow.runWidgetCommand exists",
             "must define 'func runWidgetCommand(_ cmd: WidgetCommand)' on WidgetWindow")


def test_terminal_btn_opens_palette():
    """terminalBtn.onShortPress must call showCommandPalette, not launchTerminal directly.
    The palette replaces the old single-action button behavior."""
    src = _swift_src()
    # Find the terminalBtn.onShortPress assignment
    pos = src.find("terminalBtn.onShortPress")
    if pos == -1:
        fail("terminalBtn.onShortPress calls showCommandPalette", "terminalBtn.onShortPress not found")
        return
    line = src[pos: pos + 120]
    if "showCommandPalette" in line:
        ok("terminalBtn.onShortPress calls showCommandPalette() — palette opens on single click")
    else:
        fail("terminalBtn.onShortPress calls showCommandPalette",
             f"expected showCommandPalette, found: {line!r}")


# ── Visual design invariants ──────────────────────────────────────────────────

def test_command_palette_uses_monospace_font():
    """CommandPaletteVC.showList must use monospacedSystemFont for command text rows.
    Commands should look like code — monospace gives the right visual affordance."""
    src = _extract_func(_swift_src(), "func showList()")
    if not src:
        fail("palette uses monospace font", "showList() not found in tray.swift")
        return
    if "monospacedSystemFont" in src:
        ok("CommandPaletteVC.showList uses monospacedSystemFont for command text")
    else:
        fail("palette uses monospace font",
             "showList() must use NSFont.monospacedSystemFont for the command label")


def test_command_palette_shows_terminal_icon():
    """CommandPaletteVC must render a 'terminal' SF symbol for openTerminal commands.
    This gives a quick visual distinction between open-terminal and inject-command rows."""
    src = _extract_class(_swift_src(), "CommandPaletteVC")
    if not src:
        fail("palette shows terminal icon", "CommandPaletteVC class not found")
        return
    if '"terminal"' in src and "openTerminal" in src:
        ok("CommandPaletteVC uses 'terminal' SF symbol for openTerminal commands")
    else:
        fail("palette shows terminal icon",
             "must use NSImage(systemSymbolName: \"terminal\", ...) for .openTerminal kind rows")


def test_command_palette_inline_edit_buttons():
    """CommandPaletteVC.showList must add 'pencil' icon buttons for inline editing.
    These replace the right-click context menu as the primary edit UX — always visible."""
    src = _extract_func(_swift_src(), "func showList()")
    if not src:
        fail("palette has inline pencil edit buttons", "showList() not found")
        return
    if '"pencil"' in src:
        ok("CommandPaletteVC.showList adds 'pencil' SF symbol button for inline editing")
    else:
        fail("palette has inline pencil edit buttons",
             "showList() must add NSImage(systemSymbolName: \"pencil\", ...) buttons per row")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Command Palette Tests ===\n")

    print("-- WidgetCommand struct --")
    test_widget_command_struct_exists()
    test_widget_command_has_defaults()

    print("\n-- Prefs persistence --")
    test_prefs_has_widget_commands_methods()

    print("\n-- CommandPaletteVC --")
    test_command_palette_vc_exists()
    test_command_palette_shows_list()
    test_command_palette_shows_edit()

    print("\n-- WidgetWindow integration --")
    test_command_palette_run_widget_command()
    test_terminal_btn_opens_palette()

    print("\n-- Visual design --")
    test_command_palette_uses_monospace_font()
    test_command_palette_shows_terminal_icon()
    test_command_palette_inline_edit_buttons()

    print(f"\n══════════════════════════════════")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"══════════════════════════════════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
