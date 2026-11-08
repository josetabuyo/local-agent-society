"""Dictation vocabulary: words Whisper keeps mishearing, put back right.

Whisper writes a word it doesn't expect the way it sounds to a Spanish ear:
"Wavi" comes out "guabi", "git" comes out "JIT", "JSON" comes out "yeison".
After every final transcription (the widget's 🎤, through the
backend's POST /dictation/fix) each word whose sound matches a known term is
rewritten to that term. Known terms come from three places:

  1. every LAS agent's name (+ its optional `heard_as` list in .las-agent.json)
  2. DEFAULT_TERMS / DEFAULT_HEARD below — everyday software vocabulary
  3. the user's own file, ~/.las/vocabulary.txt (`las vocab add`):
       term                 one term, matched by sound
       heard => term        an explicit spelling that sound-matching misses

Matching is deterministic (sound_key below), never a model call:
a word is rewritten only when its sound key equals exactly one term's key,
and a key two different terms share is never used.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

# ── agent names as dictation hears them ──────────────────────────────────────
#
# Whisper writes names it doesn't know the way they sound: "Wavi" comes out
# "guabi", "uabi", "wabi". Every word whose Spanish sound
# matches an agent's name is rewritten to the name, so both the model and the
# agent that receives the text read "Wavi". An agent can add spellings the
# sound key misses with `heard_as` in its .las-agent.json.

# qu before the u→w glide: the u of "que"/"qui" is silent, so "queso" is keso, not kbeso.
_DIGRAPHS = [(r"g[uü](?=[aeiou])", "w"), (r"qu(?=[ei])", "k"), (r"h?u(?=[aeio])", "w"), (r"c(?=[ei])", "s"),
             (r"ch", "x"), (r"ll", "y"), (r"c|q", "k"), (r"z", "s"), (r"h", ""), (r"[vw]", "b"), (r"j", "g"), (r"ee", "i")]


def sound_key(word: str) -> str:
    """A rough Spanish-ear phonetic key: guabi, uabi, wabi and Wavi all → "babi"."""
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(ch for ch in w if not unicodedata.combining(ch) or ch == "\u0308")
    w = w.replace("u\u0308", "ü")
    w = re.sub(r"[^a-zñü]", "", w)
    for pat, rep in _DIGRAPHS:
        w = re.sub(pat, rep, w)
    w = w.replace("y", "i")
    return re.sub(r"(.)\1+", r"\1", w)


def name_fixes(configs: dict[str, dict]) -> dict[str, str]:
    """sound key / lowercase alias → canonical agent name. Only one-word names
    of 4+ letters (short keys collide with ordinary words); a key two agents
    share is dropped — ambiguous, so never rewritten."""
    fixes: dict[str, str] = {}
    clash: set[str] = set()
    for name, cfg in configs.items():
        keys = set()
        if re.fullmatch(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü]{4,}", name):
            keys.add(sound_key(name))
        for alias in cfg.get("heard_as") or []:
            if isinstance(alias, str) and alias.strip():
                keys.add(alias.strip().lower())
        for k in keys:
            if k in fixes and fixes[k] != name:
                clash.add(k)
            fixes[k] = name
    return {k: v for k, v in fixes.items() if k not in clash}


def fix_names(text: str, fixes: dict[str, str]) -> str:
    """Rewrite each word (or multi-word heard_as alias) that sounds like an agent's name to that name."""
    for alias, name in sorted(((a, n) for a, n in fixes.items() if " " in a), key=lambda x: -len(x[0])):
        text = re.sub(rf"(?i)\b{re.escape(alias)}\b", name, text)

    def one(m: re.Match) -> str:
        word = m.group(0)
        name = fixes.get(word.lower()) or fixes.get(sound_key(word))
        return name if name and len(word) >= 3 else word   # agents need 4+ letters to get a key at all (name_fixes)
    return re.sub(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü]+", one, text)



USER_FILE = Path(os.getenv("LAS_VOCABULARY_FILE", str(Path.home() / ".las" / "vocabulary.txt")))
MIN_TERM_LEN = 3   # "git" must count; shorter keys collide with ordinary words

# Words programmers say in English mid-Spanish. Matched by SOUND
# (sound_key: b/v/w, c/k/q, z/s, ll/y, silent h… are one), so
# "bakend", "doquer", "cubernetes" all land here without listing them.
DEFAULT_TERMS = [
    # git & review
    "git", "GitHub", "GitLab", "commit", "branch", "merge", "rebase", "checkout", "stash", "tag",
    "push", "pull", "fork", "clone", "diff", "issue", "review", "reviewer", "ticket", "sprint", "hotfix", "feature",
    # architecture & web
    "backend", "frontend", "fullstack", "endpoint", "API", "JSON", "YAML", "localhost", "deploy", "staging",
    "rollback", "pipeline", "framework", "library", "package", "server", "client", "socket", "webhook",
    "cache", "query", "schema", "database", "Postgres", "SQL", "Redis", "token", "login", "logout", "online", "offline",
    # code
    "array", "string", "boolean", "null", "callback", "promise", "async", "await", "thread", "queue",
    "debug", "bug", "log", "logs", "test", "tests", "pytest", "build", "release", "linter", "refactor", "script", "prompt",
    # infra
    "Docker", "Kubernetes", "cluster", "container", "namespace", "AWS", "Lambda", "Glue", "Athena", "CDK", "S3",
    "Vercel", "SSH", "CLI", "MQTT", "broker", "bridge", "router", "Wi-Fi",
    # languages & tools
    "Python", "Node", "npm", "TypeScript", "JavaScript", "React", "Electron", "Next.js", "Vite", "Tailwind",
    "Chrome", "Mac", "iPhone", "Android", "Figma", "Slack", "WhatsApp", "Telegram", "Gmail", "Google",
    # this society
    "Claude", "Codex", "Ollama", "Whisper", "Kokoro", "vortexia", "widget", "mailbox",
]

# Spellings the sound key can't reach — how Whisper writes English words
# when told the audio is Spanish. `heard => term`, lowercase on the left.
DEFAULT_HEARD = {
    "yeison": "JSON", "yason": "JSON", "jeison": "JSON", "yéison": "JSON",
    "pul request": "pull request", "pulrequest": "pull request", "pul requés": "pull request", "pul requests": "pull requests",
    "merch request": "merge request", "mersh request": "merge request",
    "puch": "push", "push": "push", "pul": "pull",
    "merch": "merge", "mersh": "merge", "rebeis": "rebase", "ribeis": "rebase",
    "checaut": "checkout", "chequeaut": "checkout", "estash": "stash",
    "brench": "branch", "branche": "branch", "branch": "branch",
    "diploi": "deploy", "deploi": "deploy", "diployar": "deployar",
    "estaging": "staging", "esteiyin": "staging", "esteiying": "staging",
    "rolbac": "rollback", "rolbak": "rollback", "pipelain": "pipeline", "paiplain": "pipeline", "paiplein": "pipeline",
    "freimwork": "framework", "freimguork": "framework", "frameguork": "framework",
    "fitcher": "feature", "ficher": "feature", "fícher": "feature", "jotfix": "hotfix", "jot fix": "hotfix",
    "riviu": "review", "ribiu": "review", "isue": "issue", "ishu": "issue", "íshu": "issue",
    "queri": "query", "cueri": "query", "kueri": "query", "estring": "string", "arrei": "array",
    "bulean": "boolean", "colbac": "callback", "colbak": "callback", "asinc": "async", "euait": "await",
    "lainter": "linter", "linter": "linter", "eskript": "script", "escript": "script",
    "guiyet": "widget", "uiyet": "widget", "wiyet": "widget", "güiyet": "widget", "guiyed": "widget",
    "clod": "Claude", "clodio": "Claude", "cloud code": "Claude Code", "clod code": "Claude Code",
    "olama": "Ollama", "oyama": "Ollama", "guisper": "Whisper", "uisper": "Whisper",
    "enepeeme": "npm", "ene pe eme": "npm", "a pe i": "API", "ese ese ache": "SSH", "ce ele i": "CLI",
    "giraf": "GitHub", "guitjab": "GitHub", "git jab": "GitHub", "guit hub": "GitHub", "git hab": "GitHub", "guitlab": "GitLab",
    "jit": "git", "guit": "git", "yit": "git",
    "yamel": "YAML", "local jost": "localhost", "lokal jost": "localhost", "localjost": "localhost",
    "taipscript": "TypeScript", "taip escript": "TypeScript", "yavascript": "JavaScript", "java escript": "JavaScript",
    "riact": "React", "ríact": "React", "doquer": "Docker", "dóker": "Docker", "cubernetis": "Kubernetes", "kubernetis": "Kubernetes",
    "vercel": "Vercel", "bercel": "Vercel", "nextyes": "Next.js", "next yes": "Next.js", "next jei es": "Next.js",
    "cluster": "cluster", "clóster": "cluster", "uebjuk": "webhook", "güebjuk": "webhook",
}


def load_user_file(path: Path | None = None) -> tuple[list[str], dict[str, str]]:
    terms, heard = [], {}
    path = path or USER_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return terms, heard
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=>" in line:
            src, _, dst = line.partition("=>")
            if src.strip() and dst.strip():
                heard[src.strip().lower()] = dst.strip()
        else:
            terms.append(line)
    return terms, heard


def build_fixes(agent_configs: dict[str, dict], *, user_file: Path | None = None) -> dict[str, str]:
    """sound key / lowercase spelling → the term to write. Agents first, then
    the defaults, then the user's file — later explicit spellings win; a sound
    key two different terms share is dropped (ambiguous)."""
    user_terms, user_heard = load_user_file(user_file)
    fixes = dict(name_fixes(agent_configs))
    taken = {v.lower() for v in fixes.values()}
    owner: dict[str, str] = {}
    clash: set[str] = set()
    for term in DEFAULT_TERMS + user_terms:
        if len(re.sub(r"[^A-Za-z]", "", term)) < MIN_TERM_LEN or " " in term:
            continue
        key = sound_key(term)
        if len(key) < MIN_TERM_LEN or term.lower() in taken:
            continue
        if key in fixes and fixes[key].lower() != term.lower():
            clash.add(key)
            continue
        if key in owner and owner[key].lower() != term.lower():
            clash.add(key)
        owner[key] = term
    for key, term in owner.items():
        if key not in clash:
            fixes[key] = term
    fixes.update(DEFAULT_HEARD)
    fixes.update(user_heard)
    return fixes


def fix_text(text: str, fixes: dict[str, str]) -> str:
    return fix_names(text, fixes)


def add_entry(entry: str, path: Path | None = None) -> None:
    path = path or USER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.strip() + "\n")


__all__ = ["build_fixes", "fix_text", "add_entry", "load_user_file", "sound_key", "name_fixes", "fix_names", "USER_FILE", "DEFAULT_TERMS", "DEFAULT_HEARD"]
