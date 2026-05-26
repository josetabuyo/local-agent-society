#!/bin/bash
# Integration test suite for the tray widget
# Usage: bash widget/run_tests.sh

set -euo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PASS=0; FAIL=0

ok()   { echo "  PASS $1"; ((PASS++)) || true; }
fail() { echo "  FAIL $1: $2"; ((FAIL++)) || true; }

echo "=== Tray Widget Tests ==="
echo ""

# ── 1. Compile ──────────────────────────────────────────────────────────────
echo "→ Compilation"
if swiftc "$SCRIPT_DIR/tray.swift" -o /tmp/tray-test-bin 2>/tmp/tray-compile-err; then
    ok "tray.swift compiles"
else
    fail "tray.swift compiles" "$(cat /tmp/tray-compile-err)"
fi
rm -f /tmp/tray-test-bin /tmp/tray-compile-err

# ── 2. Logic unit tests ─────────────────────────────────────────────────────
echo ""
echo "→ Logic (Prefs, URL parsing, closedByUser set)"
if swift "$SCRIPT_DIR/tests_logic.swift"; then
    ok "logic tests (all passed internally)"
else
    fail "logic tests" "one or more logic assertions failed (see output above)"
fi

# ── 3. URL scheme registered with LaunchServices ────────────────────────────
echo ""
echo "→ URL scheme registration"
LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
# Dump to a temp file — avoids SIGPIPE from grep -q breaking the pipefail check
LSDUMP=$(mktemp)
"$LSREG" -dump > "$LSDUMP" 2>/dev/null || true
if grep -q "localagentsociety:" "$LSDUMP"; then
    ok "localagentsociety:// registered in LaunchServices"
else
    fail "localagentsociety:// registered" "not found — run: $LSREG -f 'widget/Local Agent Society.app'"
fi
rm -f "$LSDUMP"

# ── 4. Tray process running ──────────────────────────────────────────────────
echo ""
echo "→ Process"
if pgrep -x tray > /dev/null 2>&1; then
    ok "tray process is running"
else
    fail "tray process is running" "not found — open the app first"
fi

# ── 5. App bundle structure ──────────────────────────────────────────────────
echo ""
echo "→ App bundle"
APP="$SCRIPT_DIR/Local Agent Society.app"
[[ -f "$APP/Contents/MacOS/tray" ]]    && ok "binary exists in bundle"    || fail "binary exists in bundle" "missing"
[[ -f "$APP/Contents/Info.plist" ]]    && ok "Info.plist exists"          || fail "Info.plist exists" "missing"
grep -q "localagentsociety" "$APP/Contents/Info.plist" \
    && ok "URL scheme in Info.plist" || fail "URL scheme in Info.plist" "not found"

# ── 6. URL scheme dispatch (open + verify tray still running) ────────────────
echo ""
echo "→ URL scheme dispatch"
if pgrep -x tray > /dev/null 2>&1; then
    open "localagentsociety://__tray_test_probe__" 2>/dev/null || true
    sleep 0.5
    # Tray must still be running (didn't crash on unknown family)
    if pgrep -x tray > /dev/null 2>&1; then
        ok "tray survives unknown-family URL"
    else
        fail "tray survives unknown-family URL" "process died after open"
    fi
else
    fail "url scheme dispatch" "skipped — tray not running"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed"
echo "══════════════════════════════════"
[[ $FAIL -eq 0 ]] || exit 1
