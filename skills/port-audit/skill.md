---
name: port-audit
description: Audit the Local Agent Society port registry against what's actually running. Use `las ports audit` — this skill just invokes it and interprets results.
allowed-tools: Bash(las:*) Bash(curl:*)
---

# /port-audit — Society Port Audit

Runs `las ports audit` and remediates any violations found.

## Execution steps

### 1. Run the audit
```bash
las ports audit
```

### 2. For each VIOLATION (process on a port owned by another agent)
1. Identify the project it belongs to (check start scripts, package.json)
2. Fix the root cause in that project's config
3. Kill the violating process: `kill PID`
4. Register the correct port for that project: `las ports claim "APP" --port PORT`
5. Notify the agent via TTY injection:
   ```bash
   las agent inject AgentName "Port PORT was re-assigned to you. Update your config to use PORT." --from LocalAgentSociety
   ```

### 3. For each GHOST (registered but not running)
Report only — do not unregister. The agent may start later.

### 4. For each UNREGISTERED listener
Check which project it belongs to. If it's a known agent, have them register it:
```bash
las ports claim "DESCRIPTION" --port PORT
```

### 5. Summary
Report counts: OK / ghost / unregistered.
