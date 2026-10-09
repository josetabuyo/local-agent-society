"""Thin HTTP client for the Local Agent Society backend API.

All requests are routed through a single ``_request`` helper that
centralizes error handling (connection failures and HTTP error
responses). The public ``get``/``post``/``delete``/``patch`` functions
are thin wrappers preserving their original signatures so every caller
in ``cli/commands/*`` is unaffected.
"""

import os
import shutil
import subprocess
import sys
from typing import Any, Optional

import requests

BASE = "http://localhost:8700"
TIMEOUT_S = 5


def _handle(resp: requests.Response) -> Any:
    """Raise for HTTP error status, then return the parsed JSON body."""
    resp.raise_for_status()
    return resp.json()


SANDBOX_HINT = (
    "This process looks sandboxed without network access (a Codex session whose "
    "permissions were narrowed to workspace-only, for instance). In Codex: "
    "/permissions -> Full access, or reopen it with `las codex resume`."
)


def _port_listening(port: int) -> bool:
    """True when something is LISTENING on ``port`` — checked with lsof, which
    reads the process table and so still works inside a sandbox that denies
    the socket connect itself."""
    if not shutil.which("lsof"):
        return False
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.stdout.strip())


def _unreachable_message() -> str:
    """Why the backend can't be reached. A refused/blocked connect used to be
    reported as "backend not running" even when the backend was fine and the
    CALLER was the one cut off from the network (seen 2026-10-08: a Codex
    session narrowed to workspace-write, network off, kept retrying
    `las agent send` while `las start` said the backend was up)."""
    port = int(BASE.rsplit(":", 1)[1])
    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") == "1":
        return f"Error: can't reach the backend on :{port} — network is disabled in this Codex sandbox. {SANDBOX_HINT}"
    if _port_listening(port):
        return f"Error: the backend is running on :{port} but this process can't connect to it. {SANDBOX_HINT}"
    return "Error: backend not running. Try `las start`."


def _request(method: str, path: str, data: Optional[dict] = None) -> Any:
    """Perform an HTTP request against the backend and return the JSON body.

    Handles connection failures and HTTP errors uniformly: prints a
    user-facing message and exits the process with status 1 on failure.

    Args:
        method: HTTP method name, e.g. "get", "post", "delete", "patch".
        path: URL path (appended to ``BASE``).
        data: Optional JSON body, sent for methods that accept one
            (``post``/``patch``). Ignored by methods that don't take a body.

    Returns:
        The parsed JSON response body.
    """
    try:
        func = getattr(requests, method)
        if method in ("post", "patch", "put"):
            resp = func(f"{BASE}{path}", json=data or {}, timeout=TIMEOUT_S)
        else:
            resp = func(f"{BASE}{path}", timeout=TIMEOUT_S)
        return _handle(resp)
    except requests.ConnectionError:
        print(_unreachable_message())
        sys.exit(1)
    except requests.Timeout:
        # ReadTimeout is NOT a ConnectionError: a backend that is up but
        # starved (machine swapping, TTS synthesis hogging the process)
        # used to escape here as a raw traceback, and every fail-soft
        # caller (`las claude`'s presence step) only expects SystemExit.
        print(f"Error: backend not responding (timed out after {TIMEOUT_S}s on {method.upper()} {path}). Try `las status`.")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"Error: {e.response.status_code} {e.response.text}")
        sys.exit(1)


def get(path):
    """Send a GET request to ``path`` and return the parsed JSON response."""
    return _request("get", path)


def post(path, data=None):
    """Send a POST request to ``path`` with an optional JSON ``data`` body."""
    return _request("post", path, data)


def delete(path):
    """Send a DELETE request to ``path`` and return the parsed JSON response."""
    return _request("delete", path)


def patch(path, data=None):
    """Send a PATCH request to ``path`` with an optional JSON ``data`` body."""
    return _request("patch", path, data)


def put(path, data=None):
    """Send a PUT request to ``path`` with an optional JSON ``data`` body."""
    return _request("put", path, data)
