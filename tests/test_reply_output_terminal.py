"""A prompt typed into the terminal is a human input on the Mac: auto routing learns it."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def test_terminal_input_sends_the_voice_back_to_the_mac(tmp_path, monkeypatch):
    import main
    monkeypatch.setattr(main, "REPLY_ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr(main, "load_json", lambda p, d: ({"Alpha": {}} if p == main.REGISTRY_FILE else main.json.loads(Path(p).read_text()) if Path(p).exists() else d))
    main.save_json(main.REPLY_ROUTES_FILE, {"Alpha": "jose-iphone"})
    c = TestClient(main.app)
    assert c.post("/agents/Alpha/terminal-input", json={}).json()["learned"] == "mac"
    assert c.post("/agents/Nobody/terminal-input", json={}).status_code == 404
