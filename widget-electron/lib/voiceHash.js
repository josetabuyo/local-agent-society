'use strict';

/**
 * Deterministic, cross-platform voice assignment.
 *
 * macOS voice names ("Samantha", "Paulina", ...) referenced in CLAUDE.md do
 * not exist on Windows, so instead of pinning a specific voice name we hash
 * the agent's name into a stable index within the pool of
 * `speechSynthesis.getVoices()` entries that match the agent's locale.
 *
 * This gives two properties:
 *   1. Same agent, same machine, across restarts -> same voice (hash of the
 *      name is stable).
 *   2. Different agents usually land on different voices (not guaranteed
 *      collision-free — "probabilistically distinguishable", not unique).
 */

/**
 * FNV-1a 32-bit hash. Small, dependency-free, stable across platforms/Node
 * versions (unlike relying on String.prototype hashCode-style tricks).
 * @param {string} str
 * @returns {number} unsigned 32-bit integer
 */
function hashString(str) {
  let hash = 0x811c9dc5; // FNV offset basis
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    // hash *= 16777619 (FNV prime), done with shifts to stay in 32-bit int math
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0; // force unsigned
}

/**
 * Deterministically pick an index into `list` for `name`. Returns -1 for an
 * empty list.
 * @param {string} name
 * @param {Array} list
 */
function hashIndex(name, list) {
  if (!Array.isArray(list) || list.length === 0) return -1;
  return hashString(String(name)) % list.length;
}

/**
 * Pick a voice for an agent out of the browser/OS voice list.
 *
 * @param {string} name - agent name, used as the hash seed
 * @param {string} locale - e.g. "en-US", "es-MX"; only the language prefix
 *   (before "-") is used to filter voices
 * @param {Array<{name: string, lang: string}>} voices - result of
 *   speechSynthesis.getVoices()
 * @returns {{voice: object|null, warning: string|null}}
 */
function pickVoice(name, locale, voices) {
  const lang = String(locale || 'en').split('-')[0].toLowerCase();
  const all = Array.isArray(voices) ? voices : [];

  const matching = all.filter((v) => v && typeof v.lang === 'string' && v.lang.toLowerCase().startsWith(lang));

  if (matching.length > 0) {
    const idx = hashIndex(name, matching);
    return { voice: matching[idx], warning: null };
  }

  if (all.length > 0) {
    const idx = hashIndex(name, all);
    return {
      voice: all[idx],
      warning: `No voices found for locale "${locale}" (agent "${name}"); falling back to any available voice.`,
    };
  }

  return { voice: null, warning: `speechSynthesis.getVoices() returned no voices; cannot speak for agent "${name}".` };
}

module.exports = { hashString, hashIndex, pickVoice };
