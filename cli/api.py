import sys
import requests

BASE = "http://localhost:8700"


def _handle(resp):
    resp.raise_for_status()
    return resp.json()


def get(path):
    try:
        return _handle(requests.get(f"{BASE}{path}", timeout=5))
    except requests.ConnectionError:
        print("Error: backend not running. Try `las start`.")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"Error: {e.response.status_code} {e.response.text}")
        sys.exit(1)


def post(path, data=None):
    try:
        return _handle(requests.post(f"{BASE}{path}", json=data or {}, timeout=5))
    except requests.ConnectionError:
        print("Error: backend not running. Try `las start`.")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"Error: {e.response.status_code} {e.response.text}")
        sys.exit(1)


def delete(path):
    try:
        return _handle(requests.delete(f"{BASE}{path}", timeout=5))
    except requests.ConnectionError:
        print("Error: backend not running. Try `las start`.")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"Error: {e.response.status_code} {e.response.text}")
        sys.exit(1)


def patch(path, data=None):
    try:
        return _handle(requests.patch(f"{BASE}{path}", json=data or {}, timeout=5))
    except requests.ConnectionError:
        print("Error: backend not running. Try `las start`.")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"Error: {e.response.status_code} {e.response.text}")
        sys.exit(1)
