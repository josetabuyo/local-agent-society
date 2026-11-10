'use strict';

/**
 * contextBridge surface for the renderer. Renderer runs with
 * contextIsolation + sandbox, no direct Node/Electron access — everything it
 * needs comes through here.
 */

const { contextBridge, ipcRenderer } = require('electron');
const { pickVoice } = require('./lib/voiceHash');
const { KOKORO_VOICES, KOKORO_HASH_POOL } = require('./lib/kokoroVoices');

contextBridge.exposeInMainWorld('las', {
  /** Deterministic voice selection — see lib/voiceHash.js. */
  pickVoice: (name, locale, voices) => pickVoice(name, locale, voices),

  /** The local Kokoro voice pool (see lib/kokoroVoices.js) — plain data, fed
   * into pickVoice() in place of the old speechSynthesis.getVoices() list. */
  ttsVoices: KOKORO_VOICES,
  /** The subset an agent's name hashes into (pin-only voices left out). */
  ttsHashPool: KOKORO_HASH_POOL,

  /** Synthesize `text` with a Kokoro voice id + kokoro-onnx lang code (both
   * from ttsVoices) via the backend's /tts/synthesize; returns
   * {ok:true, wav: ArrayBuffer} or {ok:false, error}. */
  synthesizeSpeech: (text, voiceId, lang) => ipcRenderer.invoke('tts:synthesize', text, voiceId, lang),

  /** Speak-queue handshake: report one speak envelope's progress back to the
   * backend drainer (POST /queue/ack) so the NEXT agent's clip is held until
   * this one is over. phase: 'started' | 'done' | 'skipped' (+ reason). */
  ackSpeak: (id, phase, reason, durationMs) => ipcRenderer.invoke('queue:ack', id, phase, reason, durationMs),

  /** Progress pushes during synthesizeSpeech (model download/load vs.
   * inference), same shape as onAudioStatus below.
   * @param {(status: {state:string, progress?:number, file?:string}) => void} cb */
  onTtsStatus: (cb) => {
    ipcRenderer.on('tts:status', (_event, status) => cb(status));
  },

  /** Agent name this window was opened for, read from ?agent= query string. */
  getAgentName: () => new URLSearchParams(window.location.search).get('agent') || '',

  /** Write a line to session/widget.log (see main.js's persistent logging
   * section) — the renderer has no fs access, so this is the only way it
   * can leave a durable trace. level: 'debug'|'info'|'warn'|'error'. */
  log: (level, component, message) => ipcRenderer.send('log:write', level, component, message),

  getPrefs: (name) => ipcRenderer.invoke('prefs:get', name),
  setPrefs: (name, patch) => ipcRenderer.invoke('prefs:set', name, patch),
  /** Another window changed THIS agent's prefs (a friend's 🔊 in a society panel). @param {(prefs: object) => void} cb */
  onPrefsChanged: (cb) => ipcRenderer.on('prefs:changed', (_e, prefs) => cb(prefs)),
  /** `name`'s settings in a popup over `anchor` ({x, y, width, height}, screen px) — a society tile's ⚙. */
  showAgentSettings: (name, anchor) => ipcRenderer.invoke('agent:show-settings', name, anchor),
  /** Another widget asked this one to open its settings. @param {() => void} cb */
  onOpenSettings: (cb) => ipcRenderer.on('settings:open', () => cb()),

  /** Tile reconciler settings shared by every widget of this app instance
   * (main.js "tile reconciler"): heartbeat and shrink delay, in ms. get()
   * also returns `limits` and `defaults`; set() returns the clamped result. */
  getTileSettings: () => ipcRenderer.invoke('tiles:get'),
  setTileSettings: (patch) => ipcRenderer.invoke('tiles:set', patch),
  /** Another widget changed the tile settings. @param {(settings: object) => void} cb */
  onTileSettings: (cb) => ipcRenderer.on('tiles:changed', (_e, settings) => cb(settings)),

  /** Update notice: { available, behind, commits: [{sha, subject}], checked_at, error } or null (backend/updates.py). */
  getUpdateStatus: () => ipcRenderer.invoke('update:get'),
  /** Fetch the upstream now; resolves to the fresh status. */
  checkUpdate: () => ipcRenderer.invoke('update:check'),
  /** Put the update command on the clipboard; resolves to it. */
  copyUpdateCommand: () => ipcRenderer.invoke('update:copy-command'),
  /** The status changed (a new version appeared, or was installed). @param {(status: object) => void} cb */
  onUpdateStatus: (cb) => ipcRenderer.on('update:status', (_e, status) => cb(status)),

  /** Grow/shrink this window by (dw, dh) pixels — see .resize-handle in widget.css. */
  resizeBy: (dw, dh) => ipcRenderer.send('window:resize-by', dw, dh),
  /** Toggle this widget between sticky and icon size (double-click on its top strip). */
  toggleIconMode: () => ipcRenderer.send('window:toggle-icon'),
  /** Move this window by (dx, dy) — the icon face drags itself. */
  moveBy: (dx, dy) => ipcRenderer.send('window:move-by', dx, dy),
  /** Main switched this widget to icon size (true) or back to a sticky (false). @param {(on: boolean) => void} cb */
  onIconMode: (cb) => ipcRenderer.on('window:icon-mode', (_e, on) => cb(on)),
  /** The icon's popup (button bar + drawers in a window of its own): toggle it, or open it on `drawer`. From the popup: close it. */
  togglePopup: (drawer) => ipcRenderer.send('popup:toggle', drawer || null),
  /** The popup measured its button bar: its closed height. */
  popupReady: (barHeight) => ipcRenderer.send('popup:ready', barHeight),
  /** Open `drawer` in this popup (the icon asked for it). @param {(drawer: string) => void} cb */
  onPopupDrawer: (cb) => ipcRenderer.on('popup:drawer', (_e, drawer) => cb(drawer)),

  /** Grow the window to fit an overlay panel (settings),
   * or shrink it back to its remembered compact size. Idempotent.
   * `height` optionally overrides the default expanded height — the settings
   * panel is short and fixed (no scrolling list), so it asks for a smaller
   * height than the TTY-picker panel's default. */
  setExpanded: (expanded, height) => ipcRenderer.send('window:set-expanded', expanded, height),

  /** "Expand when hidden" (retired Swift "Expand on space change"): balloon
   * to fill the screen, click-through, when occluded/off-Space; shrink back
   * when visible again. See main.js's window:set-occlusion-expanded comment. */
  reportVisibility: (hidden, allowed) => ipcRenderer.send('window:report-visibility', hidden, allowed),
  /** Main decides whether this widget is grown to its mosaic tile (main.js tile reconciler) and tells the face here. */
  onOcclusionState: (cb) => ipcRenderer.on('window:occlusion-state', (_e, expanded) => cb(expanded)),

  /** @param {(envelope: object, topic: string) => void} cb */
  onVortexiaMessage: (cb) => {
    ipcRenderer.on('vortexia:message', (_event, envelope, topic) => cb(envelope, topic));
  },

  /** @param {(status: {connected: boolean, error?: string}) => void} cb */
  onVortexiaStatus: (cb) => {
    ipcRenderer.on('vortexia:status', (_event, status) => cb(status));
  },

  /** Fired after the system wakes from sleep (main.js's powerMonitor
   * 'resume' handler) — tells the renderer to re-check document.
   * visibilityState immediately instead of waiting on a fresh occlusion
   * event that may never re-fire. @param {() => void} cb */
  onSystemResume: (cb) => {
    ipcRenderer.on('system:resume', () => cb());
  },

  // ── face buttons ───────────────────────────────────────────────────────

  /** This agent's registered voice + its locale (e.g. "es-MX"), from the backend. */
  getAgentInfo: (name) => ipcRenderer.invoke('agent:info', name),

  /** Generalized "publish `text` to `toName`'s vortexia inbox" primitive. */
  vortexiaSend: (toName, text) => ipcRenderer.invoke('vortexia:send', toName, text),

  /** Human words for `toName`, optionally to ONE of its sessions ({session: sid|runtime}) — the society drawer's mic. */
  sendHuman: (toName, text, opts) => ipcRenderer.invoke('vortexia:send', toName, text, opts || null),

  /** Mic dictation -> this agent (the faithful equivalent of the retired
   * live-TTY injectToSession). No target here: WHICH of the agent's
   * sessions hears it is the agent's own `sessions.target`
   * (.las-agent.json, the children button), applied by the backend. */
  sendToSelf: (name, text) => ipcRenderer.invoke('vortexia:send', name, text),


  /** Connected runtime sessions of this agent — its children — with the
   * agent's `target`/`cc_default` choice (children button, settings). */
  getAgentSessions: (name) => ipcRenderer.invoke('agent:sessions', name),

  /** This agent's .las-agent.json as the backend reads it. */
  getAgentConfig: (name) => ipcRenderer.invoke('agent:config', name),

  /** Patch the `sessions` section of this agent's .las-agent.json
   * ({target?, cc_default?}) through the backend — the same file
   * `las agent target` writes. Resolves to the backend's config view. */
  setSessionsConfig: (name, patch) => ipcRenderer.invoke('agent:config-sessions', name, patch),
  /** Write `security_mode` ('dangerous' | 'safe') to `name`'s .las-agent.json — the key `las agent security` sets. */
  setSecurityMode: (name, mode) => ipcRenderer.invoke('agent:set-security', name, mode),

  /** Ask every intelligent session of this agent to title itself (children
   * menu refresh). Resolves to {asked, skipped} or null; the titles arrive
   * later — re-read getAgentSessions. */
  requestSessionTitles: (name) => ipcRenderer.invoke('agent:request-session-titles', name),

  /** Make one session's terminal findable (unique title + bell) and focus it
   * where the terminal app allows (Ghostty). Resolves to {ok, focused}. */
  findSession: (name, sid) => ipcRenderer.invoke('agent:session-find', name, sid),

  /** Close one session's terminal (its tty is hung up). Resolves to the
   * backend's sessions view, or null. */
  closeSession: (name, sid) => ipcRenderer.invoke('agent:session-close', name, sid),

  /** This agent's las-friends with their state: {agent, friends: [{name, registered, inactive, sessions, mutual}]} or null. */
  getFriends: (name) => ipcRenderer.invoke('agent:friends', name),
  /** The elements added to `name`'s map (`las map add`, GET /agents/{name}/map): {agent, elements:[...]} or null. */
  /** Open `name`'s map window (the 👥 click) — the same window `las map` opens. */
  openMap: (name) => ipcRenderer.invoke('map:open', name),
  getMap: (name) => ipcRenderer.invoke('agent:map', name),
  /** Remove one element (id `repo:<path>` / `url:<url>`) from `name`'s map — a map tile's ✕. */
  removeMapElement: (name, id) => ipcRenderer.invoke('agent:map-remove', name, id),
  /** A map tile's 🎤 or ⌨: the agent's own widget runs it (its recorder, its keyboard drawer), aimed at that item. */
  mapItemAction: (name, item, action) => ipcRenderer.invoke('map:item-action', name, item, action),
  /** (widget side) The map asked this widget to dictate/type to one of its items. @param {(item: object, action: string) => void} cb */
  onMapItemAction: (cb) => ipcRenderer.on('map:item-action', (_e, item, action) => cb(item, action)),
  /** Open an http(s) URL in the default browser — the map window's link/repo tiles. */
  openUrl: (url) => ipcRenderer.invoke('map:open-url', url),
  /** Link (`linked` true) or unlink `friend`; resolves to the new friends view, or null. */
  linkFriend: (name, friend, linked) => ipcRenderer.invoke('agent:friend-link', name, friend, linked),
  /** Every registered agent's name, sorted. */
  listAgentNames: () => ipcRenderer.invoke('agent:names'),
  /** Close another agent's widget, as its door button would. */
  closeAgentWidget: (name) => ipcRenderer.invoke('agent:close-widget', name),

  /** Open a detached session's log file in the OS's default viewer. */
  openSessionLog: (logPath) => ipcRenderer.invoke('agent:session-log', logPath),


  /** Local Whisper transcription (main.js's "audio transcription" section) —
   * replaces the broken Electron SpeechRecognition/webkitSpeechRecognition.
   * `pcmBuffer` must be an ArrayBuffer of mono Float32 PCM samples at 16kHz
   * (see renderer/widget.js's blobToMono16kPCM). Returns
   * {ok:true, text} or {ok:false, error}. */
  transcribeAudio: (pcmBuffer, languageHint, opts) => ipcRenderer.invoke('audio:transcribe', pcmBuffer, languageHint, opts || null),

  /** Progress/state pushes during transcribeAudio (model download/load vs.
   * actual inference), so the mic button isn't silent during first-run
   * latency. @param {(status: {state:string, progress?:number, file?:string}) => void} cb */
  onAudioStatus: (cb) => {
    ipcRenderer.on('audio:status', (_event, status) => cb(status));
  },

  /** This window started/stopped recording a dictation. Resolves to whether
   * any window is recording now (the app-wide mic gate, main.js). */
  setMicRecording: (name, recording) => ipcRenderer.invoke('mic:recording', name, recording),

  /** A speech bubble drives this widget's dictation (main.js onBubbleAction):
   * command 'start' (same as a click on the mic button), 'stop' (stop and
   * send) or 'cancel' (stop, send nothing). */
  onMicRequest: (cb) => ipcRenderer.on('mic:request', (_event, command) => cb(command || 'start')),
  /** The phases of this widget's dictation, for the bubble that asked for
   * it: listening / transcribing / sent {text} / failed {error} / cancelled / idle. */
  micStatus: (name, state, detail) => ipcRenderer.send('mic:status', name, state, detail),

  /** The app-wide mic gate changed: `held` = some window is recording, so
   * nothing may speak. @param {(held: boolean) => void} cb */
  onMicHeld: (cb) => {
    ipcRenderer.on('mic:held', (_event, held) => cb(held));
  },

  /** "Open" button: a NEW window of the default terminal ('terminal'), or
   * the file manager ('folder'), at this agent's registered directory —
   * main.js resolves the path from the backend registry. Resolves to
   * {ok, action, path, app?} or {ok:false, error}. */
  openAgent: (name, action) => ipcRenderer.invoke('agent:open', name, action),
  /** Name of the terminal app the 'terminal' open action launches (menu label). */
  getDefaultTerminalApp: () => ipcRenderer.invoke('terminal:default-app'),

  /** Clear button: types `text` (literally "/clear") into the agent's live
   * linked terminal(s) — the backend's AppleScript-via-iTerm write, not
   * vortexia messaging. */

  /** Door button: mark this agent inactive on the backend and close this
   * widget window. See main.js's agent:deactivate comment. */
  deactivateAgent: (name) => ipcRenderer.invoke('agent:deactivate', name),

  /** "Wake up via vortexia" settings checkbox — backend-synced (not
   * electron-store), same flag `las agent focus`'s wake fallback reads. */
  setWakeEnabled: (name, enabled) => ipcRenderer.invoke('agent:set-wake-enabled', name, enabled),
  getWakeEnabled: (name) => ipcRenderer.invoke('agent:get-wake-enabled', name),
});
