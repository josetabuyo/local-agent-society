/**
 * Local Agent Society — TypeScript SDK
 * Auto-generated client for the society backend (http://localhost:8700)
 */

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Agent {
  name: string;
  voice: string;
  path: string;
  backend_url: string;
  frontend_url: string;
  registered_at: string;
  [key: string]: unknown;
}

export interface AgentRegistration {
  name: string;
  voice: string;
  path: string;
  backend_url: string;
  frontend_url: string;
}

export interface Port {
  port: number;
  app: string;
  local_agent: string;
  path: string;
  registered_at: string;
}

export interface PortClaimRequest {
  port?: number;
  app: string;
  local_agent: string;
  path: string;
  start?: number;
  end?: number;
}

export interface SpeakRequest {
  text: string;
  voice: string;
  name: string;
}

export interface QueueEntry {
  text: string;
  voice: string;
  name: string;
}

export interface AttributionEntry {
  file: string;
  agent: string;
  name: string;
  timestamp: string;
  project: string;
}

export interface InjectRequest {
  message: string;
  source?: "voice" | "agent" | "external";
  from_agent?: string;
}

export interface InjectResponse {
  ok: boolean;
  injected: boolean;
  tty: string;
}

// ── Client ────────────────────────────────────────────────────────────────────

export class SocietyClient {
  private base: string;

  constructor(baseUrl = "http://localhost:8700") {
    this.base = baseUrl.replace(/\/$/, "");
  }

  private async get<T>(path: string): Promise<T> {
    const res = await fetch(`${this.base}${path}`);
    if (!res.ok) throw new SocietyError(res.status, await res.text());
    return res.json() as Promise<T>;
  }

  private async post<T>(path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new SocietyError(res.status, await res.text());
    return res.json() as Promise<T>;
  }

  private async del<T>(path: string): Promise<T> {
    const res = await fetch(`${this.base}${path}`, { method: "DELETE" });
    if (!res.ok) throw new SocietyError(res.status, await res.text());
    return res.json() as Promise<T>;
  }

  // ── Health ─────────────────────────────────────────────────────────────────

  health(): Promise<{ status: string; time: string }> {
    return this.get("/health");
  }

  // ── Agents ─────────────────────────────────────────────────────────────────

  listAgents(): Promise<Record<string, Agent>> {
    return this.get("/agents");
  }

  registerAgent(agent: AgentRegistration): Promise<{ ok: boolean; name: string }> {
    return this.post("/agents", agent);
  }

  unregisterAgent(name: string): Promise<{ ok: boolean }> {
    return this.del(`/agents/${encodeURIComponent(name)}`);
  }

  inject(agentName: string, req: InjectRequest): Promise<InjectResponse> {
    return this.post(`/agents/${encodeURIComponent(agentName)}/inject`, req);
  }

  // ── Ports ──────────────────────────────────────────────────────────────────

  listPorts(): Promise<Record<string, Port>> {
    return this.get("/ports");
  }

  registerPort(reg: Omit<Port, "registered_at">): Promise<{ ok: boolean; port: number }> {
    return this.post("/ports", reg);
  }

  /** Atomically find a free port in [start, end] and register it. */
  claimPort(req: PortClaimRequest): Promise<{ port: number }> {
    return this.post("/ports/claim", { start: 9000, end: 9999, ...req });
  }

  unregisterPort(port: number): Promise<{ ok: boolean }> {
    return this.del(`/ports/${port}`);
  }

  getFreePort(start = 9000, end = 9999): Promise<{ port: number }> {
    return this.get(`/ports/free?start=${start}&end=${end}`);
  }

  // ── Voices ─────────────────────────────────────────────────────────────────

  listVoices(): Promise<{ voices: string[] }> {
    return this.get("/voices");
  }

  randomVoice(): Promise<{ voice: string }> {
    return this.get("/voices/random");
  }

  // ── TTS Queue ──────────────────────────────────────────────────────────────

  speak(req: SpeakRequest): Promise<{ ok: boolean; queue_length: number }> {
    return this.post("/queue/speak", req);
  }

  getQueue(): Promise<QueueEntry[]> {
    return this.get("/queue");
  }

  clearQueue(): Promise<{ ok: boolean }> {
    return this.del("/queue");
  }

  // ── Attribution ────────────────────────────────────────────────────────────

  getAttribution(): Promise<AttributionEntry[]> {
    return this.get("/attribution");
  }

  addAttribution(entry: AttributionEntry): Promise<{ ok: boolean }> {
    return this.post("/attribution", entry);
  }
}

// ── Error ─────────────────────────────────────────────────────────────────────

export class SocietyError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(`Society API ${status}: ${message}`);
    this.name = "SocietyError";
  }
}

// ── Default instance ──────────────────────────────────────────────────────────

export const society = new SocietyClient();
