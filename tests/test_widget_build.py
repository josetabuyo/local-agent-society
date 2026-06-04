#!/usr/bin/env python3
"""
Verifies the Swift widget compiles without errors.
Must pass before any tray.swift change can be considered done.

Usage: python3 tests/test_widget_build.py
"""
import subprocess
import sys
import tempfile
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
SWIFT_SRC = ROOT / "widget" / "tray.swift"


def main():
    print("=== Widget Build Test ===\n")

    if not SWIFT_SRC.exists():
        print(f"FAIL  {SWIFT_SRC} not found")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        out_binary = os.path.join(tmp, "tray_test")
        cmd = [
            "swiftc", str(SWIFT_SRC),
            "-framework", "AppKit",
            "-framework", "Foundation",
            "-framework", "Speech",
            "-framework", "AVFoundation",
            "-target", "arm64-apple-macos12",
            "-o", out_binary,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print("  PASS  tray.swift compiles without errors")
            print(f"\nResults: 1 passed, 0 failed")
            sys.exit(0)
        else:
            print("  FAIL  tray.swift compilation errors:")
            for line in result.stderr.strip().splitlines():
                print(f"        {line}")
            print(f"\nResults: 0 passed, 1 failed")
            sys.exit(1)


if __name__ == "__main__":
    main()
