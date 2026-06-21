"""
Verifies the Swift widget compiles without errors.
Must pass before any tray.swift change can be considered done.
"""
import subprocess
import tempfile
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
SWIFT_SRC = ROOT / "widget" / "tray.swift"


def test_tray_swift_compiles():
    """tray.swift must compile without errors targeting arm64 macOS 12."""
    assert SWIFT_SRC.exists(), f"{SWIFT_SRC} not found"
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                "swiftc", str(SWIFT_SRC),
                "-framework", "AppKit",
                "-framework", "Foundation",
                "-framework", "Speech",
                "-framework", "AVFoundation",
                "-target", "arm64-apple-macos12",
                "-o", os.path.join(tmp, "tray_test"),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"tray.swift compilation errors:\n{result.stderr}"
