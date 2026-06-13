---
name: port-audit
description: Audit the Local Agent Society port registry against what's actually running. Finds violations (processes on ports they don't own), ghosts (registered but not running), and unregistered listeners. Fixes violations automatically.
allowed-tools: Bash(curl:*) Bash(lsof:*) Bash(ps:*) Bash(kill:*) Bash(python3:*)
---

# /port-audit — Society Port Audit

Compares the port registry against running processes. Finds and fixes violations.

## Execution steps

### 1. Fetch registry and running ports

```bash
curl -s http://localhost:8700/ports
```

```bash
curl -s http://localhost:8700/agents
```

```bash
lsof -i -P | grep LISTEN
```

### 2. Cross-reference: build the audit table

For each port in the registry, check if it's listening and by whom:
```bash
python3 -c "
import subprocess, json, sys

registry = json.loads(subprocess.check_output(['curl','-s','http://localhost:8700/ports']))
lsof_out = subprocess.check_output(['lsof','-i','-P']).decode()

# parse listening ports from lsof
listening = {}  # port -> [(proc_name, pid)]
for line in lsof_out.splitlines():
    if 'LISTEN' not in line: continue
    parts = line.split()
    if len(parts) < 9: continue
    proc, pid = parts[0], parts[1]
    addr = parts[8]
    port = addr.rsplit(':',1)[-1]
    listening.setdefault(port, []).append((proc, pid))

print('=== PORT AUDIT ===')
violations = []
ghosts = []
for port, info in sorted(registry.items(), key=lambda x: int(x[0])):
    owner = info['local_agent']
    app = info['app']
    listeners = listening.get(port, [])
    if not listeners:
        ghosts.append(port)
        print(f'  GHOST   {port:5} [{owner}] {app} — registered but not running')
    else:
        for proc, pid in listeners:
            print(f'  OK      {port:5} [{owner}] {app} — {proc} pid={pid}')

# find unregistered listeners on interesting ports
print()
print('=== UNREGISTERED LISTENERS ===')
IGNORED = {'caddy','ollama','rapportd','ControlCe','sharingd','bluetoot','useractiv','SCHelper','UserEvent'}
for port, procs in sorted(listening.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
    if port in registry: continue
    for proc, pid in procs:
        if proc in IGNORED or int(port) > 50000: continue
        print(f'  UNREG   {port:5} {proc} pid={pid} — NOT in registry')
"
```

### 3. Report and remediate

For each **VIOLATION** (process on a port owned by a different agent):
1. Identify the violating process (name, pid, which project it belongs to)
2. Kill it: `kill PID`
3. Fix the root cause in the project's config (package.json port flag, .env, start script)
4. Register the correct port for that agent via `/ports/claim`
5. Leave a message in that agent's `session/extern-inbox.md` explaining the violation and the fix

For each **GHOST** (registered but not running): report only — do not unregister unless the agent no longer exists.

For each **UNREGISTERED** listener: flag it. If it belongs to a known agent, have them register it. If unknown, report and ask the user.

### 4. Summary

Report:
- Number of ports audited
- Violations found and fixed
- Ghosts (informational)
- Unregistered listeners to investigate
