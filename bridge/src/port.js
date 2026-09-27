/**
 * Where is the broker? Same precedence as backend/vortexia_client.py's
 * resolve_mqtt_port and vortexia/src/client.js's resolvePort: the live
 * broker's own vortexia.port.json beats the port registry (whose claim can
 * be stale after a reboot race), and 1883 is the last resort.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const REGISTRY_URL = process.env.LAS_REGISTRY_URL || 'http://localhost:8700';

function vortexiaPortFile() {
  try {
    const require = createRequire(import.meta.url);
    return path.join(path.dirname(require.resolve('vortexia/package.json')), 'vortexia.port.json');
  } catch {
    return null;
  }
}

export async function resolveMqttPort({ explicit, portFile = vortexiaPortFile(), fetchImpl = globalThis.fetch, registryUrl = REGISTRY_URL } = {}) {
  if (explicit) return Number(explicit);
  if (portFile) {
    try {
      const data = JSON.parse(fs.readFileSync(portFile, 'utf8'));
      if (data.mqttPort) return Number(data.mqttPort);
    } catch {
      // fall through
    }
  }
  try {
    const res = await fetchImpl(`${registryUrl}/ports`);
    if (res.ok) {
      const ports = await res.json();
      const match = Object.values(ports).find((p) => p && p.app === 'vortexia-mqtt');
      if (match) return Number(match.port);
    }
  } catch {
    // fall through
  }
  return 1883;
}
