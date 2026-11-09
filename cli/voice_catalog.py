"""The voices LAS can speak with — Kokoro ids, one catalogue for every machine.

Every agent speaks through Kokoro (backend /tts/synthesize). Its voice is a
Kokoro id: the one it pins in `.las-agent.json` (`tts_voice`, e.g.
"em_alex+am_onyx"), or else the one its name hashes into among the voices of
its `locale` — the same choice the widget makes (widget-electron/lib/voiceHash.js).
The catalogue is widget-electron/lib/kokoroVoices.json, shared with the
widget, so an id seen in `las voices list` is an id `tts_voice` accepts, here
and on a friend's machine.

The old `voice` key (a macOS `say` name: Paulina, Samantha, …) only ever
decided the language; nothing speaks with `say` anymore. LEGACY_VOICE_LOCALES
reads an old file's language so `las agent normalize` can write `locale` and
drop the key.
"""
from __future__ import annotations

import json
from pathlib import Path

CATALOG_FILE = Path(__file__).resolve().parent.parent / "widget-electron" / "lib" / "kokoroVoices.json"

# macOS voice name → locale: only to migrate a file that still has `voice`.
LEGACY_VOICE_LOCALES = {
    "Samantha": "en-US", "Daniel": "en-GB", "Moira": "en-IE", "Karen": "en-AU",
    "Tessa": "en-ZA", "Rishi": "en-IN", "Paulina": "es-MX", "Mónica": "es-ES",
    "Jorge": "es-ES", "Flo (English (US))": "en-US", "Sandy (English (US))": "en-US",
    "Shelley (English (US))": "en-US", "Reed (English (US))": "en-US",
    "Eddy (English (US))": "en-US",
}

_FEMALE = ("af_", "bf_", "ef_")
_MALE = ("am_", "bm_", "em_")


def catalog() -> list[dict]:
    """Every Kokoro voice: {name, lang, kokoroLang, pinOnly?}, in catalogue order."""
    try:
        return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def find(voice_id: str) -> dict | None:
    return next((v for v in catalog() if v["name"] == voice_id), None)


def gender(voice_id: str) -> str:
    """"female", "male" or "mixed" — from the parts of a blend."""
    parts = {("f" if p.startswith(_FEMALE) else "m" if p.startswith(_MALE) else "?")
             for p in voice_id.split("+")}
    return "female" if parts == {"f"} else "male" if parts == {"m"} else "mixed"


def legacy_locale(voice_name: str | None) -> str | None:
    return LEGACY_VOICE_LOCALES.get(voice_name or "")


def locale_of(config: dict) -> str:
    """An agent's language: `locale`, else what its old macOS `voice` implied, else en-US."""
    return config.get("locale") or legacy_locale(config.get("voice")) or "en-US"


def _fnv1a(text: str) -> int:
    """FNV-1a 32-bit over UTF-16 code units — voiceHash.js's hashString, bit for bit."""
    h = 0x811C9DC5
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def hashed_voice(name: str, locale: str) -> str | None:
    """The voice the widget gives `name` when it pins none — voiceHash.js's pickVoice over the hash pool."""
    pool = [v for v in catalog() if not v.get("pinOnly")]
    lang = (locale or "en").split("-")[0].lower()
    matching = [v for v in pool if v["lang"].lower().startswith(lang)] or pool
    return matching[_fnv1a(str(name)) % len(matching)]["name"] if matching else None


def voice_of(name: str, config: dict) -> tuple[str | None, str]:
    """(Kokoro id, "pinned" | "hashed") — the voice `name` actually speaks with."""
    pinned = config.get("tts_voice")
    if isinstance(pinned, str) and find(pinned.strip()):
        return pinned.strip(), "pinned"
    return hashed_voice(name, locale_of(config)), "hashed"
