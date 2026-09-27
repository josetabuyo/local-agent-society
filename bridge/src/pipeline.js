/**
 * The middle of the bridge: an ordered list of interceptors that each see
 * the message before the sink does. An interceptor returns `'continue'`
 * (pass it on) or `'handled'` (stop here: the message never reaches the
 * sink). This is the seam where a future first-decision layer plugs in —
 * a local model (Pulpo) deciding whether a voice dictation should go to the
 * session at all, be answered directly, or be rewritten — without the
 * source or any sink knowing it exists (open/closed: add an interceptor,
 * change nothing else).
 *
 * ctx = { envelope, agent, reply(text), publish(topic, obj), log }
 */
import { KIND, isMicSelfTest, micSelfTestPong } from './envelope.js';

export const CONTINUE = 'continue';
export const HANDLED = 'handled';

export class Pipeline {
  constructor(interceptors = []) {
    for (const i of interceptors) {
      if (!i || typeof i.handle !== 'function' || typeof i.name !== 'string') {
        throw new TypeError('interceptor must be { name, handle(ctx) }');
      }
    }
    this.interceptors = interceptors;
  }

  /** Resolves `{ handledBy }` — the interceptor's name, or null if the sink should get it. */
  async run(ctx) {
    for (const interceptor of this.interceptors) {
      const verdict = await interceptor.handle(ctx);
      if (verdict === HANDLED) return { handledBy: interceptor.name };
    }
    return { handledBy: null };
  }
}

/** Drop a message whose `id` was already seen (QoS 1 is at-least-once). */
export function dedupInterceptor({ size = 500 } = {}) {
  const seen = [];
  const set = new Set();
  return {
    name: 'dedup',
    handle(ctx) {
      const id = ctx.envelope.id;
      if (set.has(id)) return HANDLED;
      set.add(id);
      seen.push(id);
      if (seen.length > size) set.delete(seen.shift());
      return CONTINUE;
    },
  };
}

/** Drop kinds the sink must never see (e.g. this bridge's own self-test pong). */
export function ignoreKindsInterceptor(kinds) {
  const ignored = new Set(kinds);
  return {
    name: 'ignore-kinds',
    handle: (ctx) => (ignored.has(ctx.envelope.kind) ? HANDLED : CONTINUE),
  };
}

/**
 * Sender gate — the channels docs' "gate inbound messages" advice, in
 * bridge form: a channel event lands in the model's context as text, so
 * only senders you trust should be able to put one there. `allow(envelope)`
 * decides; the default trusts the human (mic) and any agent, and refuses
 * nothing else by itself — pass a stricter `allow` for a locked-down agent.
 */
export function senderPolicyInterceptor({ allow = () => true, log = () => {} } = {}) {
  return {
    name: 'sender-policy',
    handle(ctx) {
      if (allow(ctx.envelope)) return CONTINUE;
      log(`dropped message from ${ctx.envelope.from} (sender policy)`);
      return HANDLED;
    },
  };
}

/**
 * Answer the widget's mic self-test the instant it arrives, silently —
 * proves mic -> vortexia -> a live bridge without any session's help — and
 * still pass it on, so an attached session can add its audible "OK".
 * Mirrors cli/commands/agents.py's listen (same pong envelope).
 */
export function micSelfTestInterceptor({ agent, now = Date.now } = {}) {
  return {
    name: 'mic-selftest',
    async handle(ctx) {
      if (!isMicSelfTest(ctx.envelope)) return CONTINUE;
      await ctx.publish(`las/agent/${agent}/inbox`, micSelfTestPong(agent, { now }));
      return CONTINUE;
    },
  };
}

/**
 * The remote first-decision hook. POSTs the envelope to `url` and obeys the
 * reply: `{ "action": "handled" }` swallows it, `{ "action": "continue",
 * "envelope": {...} }` forwards (optionally rewritten). Fails OPEN: if the
 * service is down, slow, or answers nonsense, the message goes through
 * untouched — a dead helper must never eat a human's dictation.
 */
export function httpInterceptor({ url, timeoutMs = 3000, fetchImpl = globalThis.fetch, log = () => {} }) {
  if (!url) throw new TypeError('httpInterceptor needs a url');
  return {
    name: 'http',
    async handle(ctx) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const res = await fetchImpl(url, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ agent: ctx.agent, envelope: ctx.envelope }),
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const verdict = await res.json();
        if (verdict && verdict.action === HANDLED) return HANDLED;
        if (verdict && verdict.envelope && typeof verdict.envelope === 'object') {
          ctx.envelope = { ...ctx.envelope, ...verdict.envelope };
        }
        return CONTINUE;
      } catch (err) {
        log(`http interceptor ${url} failed open: ${err && err.message ? err.message : err}`);
        return CONTINUE;
      } finally {
        clearTimeout(timer);
      }
    },
  };
}

export { KIND };
