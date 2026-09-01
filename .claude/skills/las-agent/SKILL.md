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

### Registro de presencia y mensajes pendientes (vortexia)

Si `.agent.json` existe, ejecutar esto una sola vez al cargar el skill:

```bash
las agent register            # publica presencia "online" (retained) en vortexia
las agent poll --timeout 2    # drena el inbox de vortexia y muestra mensajes pendientes
```

`las agent poll` reemplaza la vieja inyección directa en la terminal: los mensajes de otros agentes ya no llegan solos, hay que pedirlos. Si `poll` devuelve mensajes pendientes, tratarlos como si acabaran de llegar — mencionarlos al usuario o actuar según corresponda antes de continuar con la tarea. Si vortexia no está corriendo, ambos comandos fallan sin romper la sesión (fail soft); simplemente no habrá mensajes.

### Escucha en vivo (obligatorio, no opcional)

Además del poll inicial, dejar corriendo un escucha en vivo para el resto de la sesión — esto es lo que permite que un dictado desde el widget (o un `las agent inject` de otro agente) llegue a esta sesión apenas se manda, sin depender de que alguien pida un poll manual. Es parte estándar de cómo arranca cualquier sesión con `.agent.json`, no algo puntual para una conversación en particular.

Con la tool `Monitor` (si está disponible en este entorno):

```
Monitor({
  description: "Dictado en vivo de <nombre_agente> (las agent listen)",
  command: "las agent listen <nombre_agente>",
  persistent: true,
  timeout_ms: 3600000,
})
```

`las agent listen` se queda conectado a vortexia y emite una línea JSON por mensaje apenas llega — cada línea genera una notificación de Monitor en esta sesión. Consume el mensaje al recibirlo (limpia el retained flag), así que mientras el listener esté activo, la entrega en vivo reemplaza al poll — un `las agent poll` posterior no va a volver a ver el mismo mensaje.

Si `Monitor` no está disponible en este entorno, no bloquear el arranque de la sesión por esto — seguir solo con el poll inicial y avisar al usuario que la entrega en vivo no está activa en esta sesión.

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

### Reporte de cierre — resumen breve al final de cada respuesta (obligatorio)

Ya no existe el hook global de `Stop` (`~/.claude/hooks/announce-here.sh`) que anunciaba un genérico "Here! `<Nombre>`" sin contenido real — fue removido de `~/.claude/settings.json`. Esa responsabilidad pasa a esta sesión: **antes de devolver el control al usuario, hablar un resumen breve de lo que se acaba de hacer.** Esto es lo que deja, en el historial de mensajes del widget, un registro útil de lo que el agente fue haciendo — no solo "está vivo", sino "hizo esto".

**Formato (plantilla con slot, no un texto fijo):**

```
"<verbo de reporte>: <resumen>. <NombreAgente>."
```

- `<verbo de reporte>` es `"Reporting"` en inglés / `"Reportando"` en español, según el idioma de la voz (ver tabla arriba).
- `<resumen>` es UNA frase de lo que se acaba de hacer, en el idioma de la voz, truncada a `report_max_chars` caracteres.
  - Leer `report_max_chars` de `.agent.json`. **Si el campo no existe, usar 40 por defecto.**
  - **Fallback duro** (nunca dejar el slot vacío): si no hay nada sustancial que resumir — turno de solo charla, pregunta sin acción, etc. — usar `"done"` (inglés) / `"listo"` (español) como `<resumen>`.
- `<NombreAgente>` es el `name` de `.agent.json`.

```bash
# inglés, voz Samantha, report_max_chars: 40
las speak "Reporting: widget chat bubbles done. LocalAgentSociety." --name LocalAgentSociety

# español, voz Paulina
las speak "Reportando: base de datos migrada. Robotics." --name Robotics
```

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

### Comunicación entre agentes (vía vortexia)

La mensajería entre agentes va sobre **vortexia** (broker MQTT local, proyecto hermano — ver `vortexia/PROTOCOL.md`), no inyección de terminal. `las agent inject` publica en el inbox de vortexia del destinatario; no escribe nada en su terminal.

```bash
# Enviar mensaje al inbox de vortexia de otro agente
las agent inject <NombreAgente> "<mensaje>" --from <EsteAgente>

# Drenar mi propio inbox de vortexia (mensajes pendientes)
las agent poll [<MiNombre>] --timeout 2

# Anunciar presencia online en vortexia (ya se hace al inicio del skill)
las agent register [<MiNombre>]

# Hablar por TTS como este agente
las speak "<texto en idioma de la voz>" --name <NombreAgente>

# Traer la ventana de otro agente al frente
las agent focus <NombreAgente>

# Estado completo de la sociedad
las status
```

La entrega **no está garantizada**: vortexia no retiene mensajes de inbox, así que el destinatario solo los ve si algo está haciendo poll en ese momento (típicamente, el skill `/las-agent` al inicio de su próxima sesión). No hay cola en disco ni reintento automático.

### Issues conocidos

**Rosetta / Node x86_64** — Pulpo y NeuroFlow tienen `node_modules` instalados con Node Intel (`~/.nvm/versions/node/v20.20.2` es x86_64). El `@esbuild/darwin-x64` corre bajo Rosetta. Fix pendiente:
```bash
arch -arm64 nvm install 20 && nvm use 20 && rm -rf node_modules && npm install
```

**Wavi Chrome renderers** — Wavi corre múltiples instancias de Chrome headless para WhatsApp. CPU alta de renderers con `--user-data-dir=.../wavi/data/sessions/` es normal, no es una amenaza.

**playwright-mcp zombies** — Cada terminal Claude puede acumular procesos `node playwright-mcp --browser chromium`. Son seguros de matar.
