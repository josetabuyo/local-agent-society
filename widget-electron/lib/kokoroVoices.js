'use strict';

/**
 * The voice pool `pickVoice` (see voiceHash.js) hashes agents into. Synthesis
 * itself runs in the backend (Python, kokoro-onnx — see backend/main.py's
 * "local text-to-speech" section and main.js's synthesizeSpeech()); this is
 * just the list of voice ids it accepts, plus the `lang` kokoro-onnx expects
 * for each (its phonemizer needs the language explicitly, it isn't inferred
 * from the voice id).
 *
 * English + Spanish only for now — the only locales any agent in this
 * society actually uses (see CLAUDE.md's voice table). kokoro-onnx ships 54
 * voices across 9 languages; the rest (French, Hindi, Italian, Japanese,
 * Portuguese, Chinese) can be added here later if an agent ever needs one —
 * no other code changes required, pickVoice already treats this as a plain
 * data list.
 */
// The catalogue itself lives in kokoroVoices.json — one list shared with the
// backend (`las voices list`, /voices), so the ids a person sees there are
// exactly the ids `tts_voice` accepts here. Comments on the data:
//   - Kokoro has only three Spanish voices; "a+b" is an equal-weight blend of
//     their style vectors (backend kokoro_voice_style), a distinct voice.
//   - pinOnly: blends with English voices (ef_dora+af_*, em_alex+am_*, …),
//     spoken with the Spanish phonemizer. An agent gets one only by pinning it
//     (`tts_voice`); the name hash never lands on them, so adding them moves
//     no agent's hashed voice.
const KOKORO_VOICES = Object.freeze(require('./kokoroVoices.json').map((v) => Object.freeze(v)));

/** The voices an agent's name hashes into — every voice except the pin-only ones. */
const KOKORO_HASH_POOL = Object.freeze(KOKORO_VOICES.filter((v) => !v.pinOnly));

module.exports = { KOKORO_VOICES, KOKORO_HASH_POOL };
