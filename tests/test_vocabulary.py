"""Dictation vocabulary (cli/vocabulary.py, POST /dictation/fix): words Whisper
mishears — agent names, dev terms, the user's own file — put back right."""
import json
import sys
import threading as _threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from cli import vocabulary as vocab
sr = vocab   # name helpers live here now


class _NoStartThread(_threading.Thread):
    def start(self):
        pass


@pytest.fixture
def backend(tmp_path, monkeypatch):
    if "backend.main" in sys.modules:
        del sys.modules["backend.main"]
    monkeypatch.setattr(_threading, "Thread", _NoStartThread)
    import backend.main as main
    monkeypatch.undo()
    for attr in ("REGISTRY_FILE", "SESSIONS_FILE", "INACTIVE_FILE", "WAKE_ENABLED_FILE"):
        monkeypatch.setattr(main, attr, tmp_path / f"{attr.lower()}.json")
    published = []
    monkeypatch.setattr(main, "_vortexia_publish",
                        lambda topic, envelope, retain=False: (published.append((topic, envelope)), True)[1])
    main._published = published
    registry = {}
    for name, desc in {"LocalAgentSociety": "widget, mic, ports", "Wavi": "WhatsApp automation", "Mute": None}.items():
        folder = tmp_path / name
        folder.mkdir()
        (folder / ".las-agent.json").write_text(json.dumps({"name": name, **({"long_description": desc} if desc else {})}))
        registry[name] = {"name": name, "path": str(folder), "voice": "Paulina"}
    main.save_json(main.REGISTRY_FILE, registry)
    return main


def test_whisper_spellings_of_wavi_become_wavi():
    fixes = sr.name_fixes({"Wavi": {}, "System": {}, "Pulpo": {}})
    for heard in ("guabi", "Guabi", "uabi", "wabi", "huabi", "wavi"):
        assert sr.fix_names(f"mandar un mensaje con {heard}", fixes) == "mandar un mensaje con Wavi"


def test_ordinary_words_are_left_alone():
    fixes = sr.name_fixes({"System": {}, "Forti": {}, "Teli": {}})
    text = "el sistema anda lento, algo fuerte en la tele"
    assert sr.fix_names(text, fixes) == text


def test_heard_as_aliases_and_ambiguous_keys():
    fixes = sr.name_fixes({"RuGIAR": {"heard_as": ["robot universidad", "rugiar"]}, "Baby": {}, "Wavi": {}})
    assert sr.fix_names("hablale a robot universidad", fixes) == "hablale a RuGIAR"
    assert "babi" not in fixes   # Baby and Wavi share the key: ambiguous, never rewritten
    assert sr.fix_names("con guabi", fixes) == "con guabi"


def test_vocabulary_fixes_spanglish_dev_terms(tmp_path):
    fixes = vocab.build_fixes({"Wavi": {}}, user_file=tmp_path / "none.txt")
    assert vocab.fix_text("hacé un commit en JIT y abrí el pul request en guit hub", fixes) == \
        "hacé un commit en git y abrí el pull request en GitHub"
    assert vocab.fix_text("el bakend manda el yeison", fixes) == "el backend manda el JSON"
    assert vocab.fix_text("con guabi", fixes) == "con Wavi"


def test_vocabulary_leaves_plain_spanish_alone(tmp_path):
    fixes = vocab.build_fixes({"System": {}, "Forti": {}, "Teli": {}}, user_file=tmp_path / "none.txt")
    text = "la casa, la fuente del sistema, el cliente pagó, la cola del banco, quiero comer pasta"
    assert vocab.fix_text(text, fixes) == text


def test_user_vocabulary_file(tmp_path):
    f = tmp_path / "vocabulary.txt"
    vocab.add_entry("Supabase", f)
    vocab.add_entry("supa beis => Supabase   # how it comes out", f)
    fixes = vocab.build_fixes({}, user_file=f)
    assert vocab.fix_text("conectá supa beis", fixes) == "conectá Supabase"
    assert vocab.fix_text("conectá supabase", fixes) == "conectá Supabase"   # a plain term: matched by sound


def test_dictation_fix_endpoint_uses_the_live_agent_names(backend, monkeypatch, tmp_path):
    monkeypatch.setattr(vocab, "USER_FILE", tmp_path / "none.txt")
    c = TestClient(backend.app)
    assert c.post("/dictation/fix", json={"text": "decile a guabi"}).json() == {"text": "decile a Wavi", "changed": True}
    assert c.post("/dictation/fix", json={"text": "hola"}).json() == {"text": "hola", "changed": False}
