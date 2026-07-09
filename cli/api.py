"""Thin HTTP client for the Local Agent Society backend API.

All requests are routed through a single ``_request`` helper that
centralizes error handling (connection failures and HTTP error
responses). The public ``get``/``post``/``delete``/``patch`` functions
are thin wrappers preserving their original signatures so every caller
in ``cli/commands/*`` is unaffected.
"""

import sys
from typing import Any, Optional

import requests

BASE = "http://localhost:8700"


def _handle(resp: requests.Response) -> Any:
    """Raise for HTTP error status, then return the parsed JSON body."""
    resp.raise_for_status()
    return resp.json()


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
        if method in ("post", "patch"):
            resp = func(f"{BASE}{path}", json=data or {}, timeout=5)
        else:
            resp = func(f"{BASE}{path}", timeout=5)
        return _handle(resp)
    except requests.ConnectionError:
        print("Error: backend not running. Try `las start`.")
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
