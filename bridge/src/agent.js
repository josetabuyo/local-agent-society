/**
 * Which agent is this? Walk up from `cwd` to the nearest `.las-agent.json`
 * — the same rule the `las` CLI applies
 * (cli/path_utils.py find_nearest_agent_dir / cli/commands/_agent_common.py).
 */
import fs from 'node:fs';
import path from 'node:path';

export const AGENT_CONFIG_FILENAMES = ['.las-agent.json'];

export function findAgentConfig(startDir, { maxDepth = 5 } = {}) {
  let dir = path.resolve(startDir);
  for (let depth = 0; depth <= maxDepth; depth++) {
    for (const filename of AGENT_CONFIG_FILENAMES) {
      const candidate = path.join(dir, filename);
      if (fs.existsSync(candidate)) return candidate;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

/**
 * Resolve `{ name, dir, config }`. An explicit `name` wins; otherwise the
 * nearest config upward from `cwd`. Throws when neither yields a name.
 */
export function resolveAgent({ name, cwd = process.cwd() } = {}) {
  const configPath = findAgentConfig(cwd);
  let config = {};
  if (configPath) {
    try {
      config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    } catch {
      config = {};
    }
  }
  const resolved = name || config.name;
  if (!resolved) {
    throw new Error(`no agent name given and no ${AGENT_CONFIG_FILENAMES.join('/')} found upward from ${cwd}`);
  }
  return { name: resolved, dir: configPath ? path.dirname(configPath) : path.resolve(cwd), config };
}
