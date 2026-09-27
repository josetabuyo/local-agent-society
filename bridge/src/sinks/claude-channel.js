/**
 * ClaudeChannelSink — delivers into a running Claude Code session through
 * its "channels" mechanism: this process IS an MCP server (stdio) that
 * declares the `claude/channel` capability and pushes each message as a
 * `notifications/claude/channel` event. Claude Code queues events into the
 * session in order and hands them to the model as
 * `<channel source="las" sender="..." ...>text</channel>`, whether the
 * session is idle at the prompt or busy (then they're batched into the
 * next turn). No Monitor, no polling, no 30-minute re-arm.
 *
 * Arming — why the mailbox is NOT consumed right away: Claude Code only
 * honors the channel when the session was started with the channel flag
 * (`--dangerously-load-development-channels server:las` during the
 * research preview). Without it this server still runs as an ordinary
 * MCP server and every event is dropped silently, with no error back —
 * consuming the mailbox then would be a black hole. So on initialize the
 * sink pushes a probe event and waits for the model to call
 * `las_channel_ack` with its id: the first proven end-to-end round trip
 * arms the sink, and only then does the bridge attach the mailbox. Same
 * principle as the widget's mic self-test: never claim a path works until
 * something on the far end answered through it.
 */
import crypto from 'node:crypto';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { KIND } from '../envelope.js';

export const SERVER_NAME = 'las';
export const CHANNEL_NOTIFICATION = 'notifications/claude/channel';
export const PROBE_PREFIX = '[las-channel-probe]';
export const ACK_TOOL = 'las_channel_ack';
export const REPLY_TOOL = 'reply';
export const STATUS_TOOL = 'las_status';

export function instructionsFor(agent) {
  return (
    `This is the Local Agent Society channel for the agent "${agent}". ` +
    'Messages from the widget mic (dictation), from other agents, and from external processes arrive as ' +
    '<channel source="las" sender="<who>" origin="human|agent|system" kind="<kind>" msg_id="..." ts="...">text</channel>. ' +
    'Treat them as if the human had typed them, per the /las-agent skill: act, then report as usual. ' +
    `To answer another agent, call the "${REPLY_TOOL}" tool with to=<sender> — never assume the sender reads this terminal. ` +
    `An event with kind="probe" is a liveness check, not a message: immediately call the "${ACK_TOOL}" tool with its probe_id ` +
    'and say nothing about it. Until that ack, no mailbox message is delivered to this session.'
  );
}

export class ClaudeChannelSink {
  constructor({ agent, send, log = () => {}, probeIntervalMs = 60_000, version = '0.1.0', randomId = () => crypto.randomBytes(3).toString('hex') }) {
    if (!agent) throw new TypeError('ClaudeChannelSink needs an agent name');
    this.name = 'claude-channel';
    this.agent = agent;
    this.send = send;
    this.log = log;
    this.probeIntervalMs = probeIntervalMs;
    this.randomId = randomId;
    this.armed = false;
    this.probeId = null;
    this.probesSent = 0;
    this.delivered = 0;
    this.onclose = null;
    this._armedWaiters = [];
    this._probeTimer = null;

    this.server = new Server(
      { name: SERVER_NAME, version },
      { capabilities: { experimental: { 'claude/channel': {} }, tools: {} }, instructions: instructionsFor(agent) },
    );
    this.server.oninitialized = () => this._onInitialized();
    this.server.onclose = () => {
      this._stopProbing();
      if (this.onclose) this.onclose();
    };
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: this.tools() }));
    this.server.setRequestHandler(CallToolRequestSchema, async (req) => this.callTool(req.params.name, req.params.arguments || {}));
  }

  tools() {
    return [
      {
        name: ACK_TOOL,
        description: 'Acknowledge a LAS channel probe. Call it with the probe_id from a kind="probe" channel event; this arms mailbox delivery into this session.',
        inputSchema: { type: 'object', properties: { probe_id: { type: 'string' } }, required: ['probe_id'] },
      },
      {
        name: REPLY_TOOL,
        description: `Send a message to another Local Agent Society agent over vortexia (as ${this.agent}). Use the sender attribute of the channel event as "to".`,
        inputSchema: { type: 'object', properties: { to: { type: 'string' }, text: { type: 'string' } }, required: ['to', 'text'] },
      },
      {
        name: STATUS_TOOL,
        description: 'Report whether this LAS channel is armed (delivering the mailbox) and how many messages it delivered.',
        inputSchema: { type: 'object', properties: {} },
      },
    ];
  }

  async callTool(name, args) {
    const text = (t) => ({ content: [{ type: 'text', text: t }] });
    switch (name) {
      case ACK_TOOL: {
        const id = String(args.probe_id || '');
        if (!this.probeId || id !== this.probeId) {
          return { ...text(`unknown probe_id ${id || '(empty)'}; current probe is ${this.probeId || 'none'}`), isError: true };
        }
        this._arm();
        return text(`armed: mailbox for ${this.agent} now delivers into this session`);
      }
      case REPLY_TOOL: {
        if (!this.send) return { ...text('no sender configured'), isError: true };
        try {
          await this.send(String(args.to || ''), String(args.text || ''));
          return text(`sent to ${args.to}`);
        } catch (err) {
          return { ...text(`send failed: ${err && err.message ? err.message : err}`), isError: true };
        }
      }
      case STATUS_TOOL:
        return text(JSON.stringify(this.status()));
      default:
        return { ...text(`unknown tool ${name}`), isError: true };
    }
  }

  status() {
    return { agent: this.agent, sink: this.name, armed: this.armed, delivered: this.delivered, probesSent: this.probesSent, probeId: this.probeId };
  }

  async start(transport = new StdioServerTransport()) {
    await this.server.connect(transport);
    return this;
  }

  /** Resolves once the model acked a probe (immediately if already armed). */
  waitArmed() {
    if (this.armed) return Promise.resolve();
    return new Promise((resolve) => this._armedWaiters.push(resolve));
  }

  _onInitialized() {
    this.log(`${this.agent}: Claude Code connected — probing the channel`);
    this.sendProbe().catch((err) => this.log(`probe failed: ${err && err.message ? err.message : err}`));
    this._stopProbing();
    this._probeTimer = setInterval(() => {
      if (this.armed) return this._stopProbing();
      this.sendProbe().catch((err) => this.log(`probe failed: ${err && err.message ? err.message : err}`));
    }, this.probeIntervalMs);
    this._probeTimer.unref?.();
  }

  _stopProbing() {
    if (this._probeTimer) clearInterval(this._probeTimer);
    this._probeTimer = null;
  }

  _arm() {
    this.armed = true;
    this._stopProbing();
    this.log(`${this.agent}: channel armed by probe ${this.probeId}`);
    const waiters = this._armedWaiters;
    this._armedWaiters = [];
    for (const resolve of waiters) resolve();
  }

  async sendProbe() {
    this.probeId = this.randomId();
    this.probesSent += 1;
    await this.server.notification({
      method: CHANNEL_NOTIFICATION,
      params: {
        content: `${PROBE_PREFIX} probe_id=${this.probeId} — call the ${ACK_TOOL} tool with this probe_id, then say nothing about it.`,
        meta: { kind: KIND.PROBE, probe_id: this.probeId, agent: this.agent },
      },
    });
  }

  async deliver(ctx) {
    const e = ctx.envelope;
    await this.server.notification({
      method: CHANNEL_NOTIFICATION,
      params: {
        content: e.text,
        // meta keys must be identifiers (letters/digits/underscore); `source`
        // is taken by Claude Code for the server name, hence sender/origin.
        meta: { kind: e.kind, sender: e.from, origin: e.source, msg_id: e.id, ts: String(e.ts), agent: ctx.agent },
      },
    });
    this.delivered += 1;
  }

  async stop() {
    this._stopProbing();
    await this.server.close();
  }
}
