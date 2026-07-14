---
name: las-agent
description: Integración con la CLI "las" del Local Agent Society — leer .agent.json, usar TTS con las speak, gestionar puertos, y contexto completo de la sociedad (quiénes son, qué corren, issues conocidos).
allowed-tools: Bash(las:*) Bash(cat:*)
---

# /las-agent — Integración con la CLI de Local Agent Society

Activa este skill al inicio de una sesión para habilitar TTS, lectura de agente local y seguridad de puertos vía la CLI `las`.

---

## 1. Verificar agente LAS en el directorio actual

```bash
cat .agent.json 2>/dev/null
```

- **Si existe:** leer `name`, `voice` y `locale`. Todos los anuncios TTS de esta sesión deben usar:
  ```bash
  las speak "<texto>" --name <nombre_agente>
  ```
  Nunca llamar directamente a la cola HTTP (`POST /queue/speak`). Solo el modelo de entrada (protagonista) habla — los sub-agentes Haiku y Opus son siempre silenciosos.
- **Si no existe:** sin integración LAS esta sesión. Comportamiento estándar.

### Idioma del TTS — obligatorio hacer match con la voz

El motor TTS solo suena natural cuando el texto está en el idioma de la voz. **Nunca mezclar idiomas.**

| Voces                                                | Idioma del texto |
|------------------------------------------------------|-----------------|
| Samantha, Daniel, Moira, Karen, Tessa, Rishi, Flo, Sandy, Shelley, Reed, Eddy, Zoe, Nicky, Evan (y variantes `en-*`) | **Inglés** |
| Paulina, Mónica (y variantes `es-*`)                 | **Español**     |

**Cómo determinar el idioma en la sesión:**

1. Si `.agent.json` tiene `"locale"`: usar ese locale (`en-*` → inglés, `es-*` → español).
2. Si no hay `locale`, derivar de `voice` con la tabla anterior.
3. Por defecto si ninguno está disponible: **inglés**.

**Regla de oro:** el texto que pases a `las speak` siempre debe estar en el idioma que corresponde a la voz del agente. Si la voz es Samantha, habla en inglés. Si es Paulina, habla en español. Aunque el usuario te escriba en otro idioma, el TTS va en el idioma de la voz.

---

## 2. Sin artefactos de sesión — nunca

No crear ninguno de los siguientes, sin importar la complejidad:
- Carpetas `session/`, `inbox/`, `outbox/`
- Archivos de log, `.txt` u otros para comunicación entre agentes
- Archivos de estado para rastrear progreso de la conversación

Toda la comunicación entre agentes ocurre vía el valor de retorno de la herramienta `Agent`, en memoria dentro de la conversación.

---

## 3. Seguridad de puertos LAS (antes de arrancar cualquier servidor)

Siempre ejecutar estos pasos antes de iniciar cualquier servidor HTTP o servicio:

```bash
# 1. Verificar conflictos
las ports audit

# 2. Obtener un puerto libre
las ports free

# 3. Reclamarlo
las ports claim "<descripción>" --port <PUERTO>
```

Nunca hardcodear un puerto que no esté en el registro LAS. Si un puerto está tomado por otro agente LAS, inyectar un mensaje y esperar:

```bash
las agent inject <OtroAgente> "Port <PUERTO> is needed — can you release it?" --from <EsteAgente>
```

---

## 4. Sociedad — quiénes somos

> **MANTENER ACTUALIZADO:** esta tabla vive en el repo de `local-agent-society`. Cada vez que se agrega, elimina o modifica un agente, actualizar aquí también.

| Agente | Voz | Path | Stack | Puertos |
|--------|-----|------|-------|---------|
| LocalAgentSociety | Samantha (EN) | `local-agent-society` | — | 8700 |
| Garantido | Daniel (EN) | `Garantido` | Next.js 16 + Turbopack | 8765, 8010, 9001 |
| NeuroFlow | Moira (EN) | `NeuroFlow` | Vite frontend | 5181, 8510 |
| Forti | Mónica (ES) | `Forti` | — | — |
| Pulpo | Tessa (EN) | `pulpo` | Vite frontend + Python backend | 5173, 8000, 9004 |
| HomeControl | Shelley (EN) | `home-control` | — | — |
| Wavi | Flo (EN) | `wavi` | Chrome headless (WhatsApp automation) | 9200–9233 |
| Minis App Acces | Sandy (EN) | `Ctrol_Acc_Mv2026` | — | — |
| System | Reed (EN) | `System` | Monitor de infraestructura | — |
| Teli | Rishi (EN) | `teli` | Telegram automation | — |
| Robotics | Paulina (ES) | `Robotics` | — | — |
| LocalModels | Eddy (EN) | `local-models` | Ollama + gemma4:e4b, API :11434 | 9002 |
| Luganense | Jorge (ES) | `Luganense` | Next.js | 9003 |

### Comunicación entre agentes

```bash
# Inyectar mensaje en la terminal de otro agente
las agent inject <NombreAgente> "<mensaje>" --from <EsteAgente>

# Hablar por TTS como este agente
las speak "<texto en idioma de la voz>" --name <NombreAgente>

# Traer la ventana de otro agente al frente
las agent focus <NombreAgente>

# Estado completo de la sociedad
las status
```

### Issues conocidos

**Rosetta / Node x86_64** — Pulpo y NeuroFlow tienen `node_modules` instalados con Node Intel (`~/.nvm/versions/node/v20.20.2` es x86_64). El `@esbuild/darwin-x64` corre bajo Rosetta. Fix pendiente:
```bash
arch -arm64 nvm install 20 && nvm use 20 && rm -rf node_modules && npm install
```

**Wavi Chrome renderers** — Wavi corre múltiples instancias de Chrome headless para WhatsApp. CPU alta de renderers con `--user-data-dir=.../wavi/data/sessions/` es normal, no es una amenaza.

**playwright-mcp zombies** — Cada terminal Claude puede acumular procesos `node playwright-mcp --browser chromium`. Son seguros de matar.
