/**
 * Where a detached session's answer goes (docs/adr/0006) — shared by the
 * per-message ExecSink and the long-lived ProcSink so the rule lives once:
 *
 *   - to another agent → sent to it, like any reply;
 *   - to this session's own agent, answering the mic (origin human) → SPOKEN in
 *     the agent's voice (it also lands in the widget's history): the human
 *     dictated it and is waiting;
 *   - to its own agent otherwise → only logged: that mailbox may be this very
 *     session, and an echo would loop forever.
 */
const HUMAN_ORIGINS = new Set(['human', 'voice']);

export function makeAnswer({ agent, send, speak = null, out = process.stderr }) {
  return async function answer({ to, text, origin }) {
    if (!to) throw new Error('an answer with no recipient');
    if (to !== agent) return send(to, text);
    if (HUMAN_ORIGINS.has(origin) && speak) {
      await speak(text);
      out.write(`[spoken to the human] ${text}\n`);
      return;
    }
    out.write(`[reply to self, not sent] ${text}\n`);
  };
}

/** POST the backend's speech queue as `agent`, in its own voice. */
export function makeSpeaker({ agent, voice, fetchImpl = globalThis.fetch, registryUrl = process.env.LAS_REGISTRY_URL || 'http://localhost:8700' }) {
  return async function speak(text) {
    const res = await fetchImpl(`${registryUrl}/queue/speak`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, voice: voice || 'Samantha', name: agent }),
    });
    if (!res.ok) throw new Error(`speak failed: HTTP ${res.status}`);
  };
}
