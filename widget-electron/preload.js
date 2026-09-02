'use strict';

/**
 * contextBridge surface for the renderer. Renderer runs with
 * contextIsolation + sandbox, no direct Node/Electron access — everything it
 * needs comes through here.
 */

const { contextBridge, ipcRenderer } = require('electron');
const { pickVoice } = require('./lib/voiceHash');

contextBridge.exposeInMainWorld('las', {
  /** Deterministic voice selection — see lib/voiceHash.js. */
  pickVoice: (name, locale, voices) => pickVoice(name, locale, voices),

  /** Agent name this window was opened for, read from ?agent= query string. */
  getAgentName: () => new URLSearchParams(window.location.search).get('agent') || '',

  /** Write a line to session/widget.log (see main.js's persistent logging
   * section) — the renderer has no fs access, so this is the only way it
   * can leave a durable trace. level: 'debug'|'info'|'warn'|'error'. */
  log: (level, component, message) => ipcRenderer.send('log:write', level, component, message),

  getPrefs: (name) => ipcRenderer.invoke('prefs:get', name),
  setPrefs: (name, patch) => ipcRenderer.invoke('prefs:set', name, patch),

  /** Grow/shrink this window by (dw, dh) pixels — see .resize-handle in widget.css. */
  resizeBy: (dw, dh) => ipcRenderer.send('window:resize-by', dw, dh),

  /** Grow the window to fit an overlay panel (settings/commands/TTY picker),
   * or shrink it back to its remembered compact size. Idempotent.
   * `height` optionally overrides the default expanded height — the settings
   * panel is short and fixed (no scrolling list), so it asks for a smaller
   * height than the commands/TTY-picker panels' default. */
  setExpanded: (expanded, height) => ipcRenderer.send('window:set-expanded', expanded, height),

  /** "Expand when hidden" (retired Swift "Expand on space change"): balloon
   * to fill the screen, click-through, when occluded/off-Space; shrink back
   * when visible again. See main.js's window:set-occlusion-expanded comment. */
  setOcclusionExpanded: (expanded) => ipcRenderer.send('window:set-occlusion-expanded', expanded),

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

  /** Mic dictation -> this agent's own inbox (the faithful equivalent of the
   * retired live-TTY injectToSession). Thin wrapper over vortexiaSend. */
  sendToSelf: (name, text) => ipcRenderer.invoke('vortexia:send', name, text),

  /** Local Whisper transcription (main.js's "audio transcription" section) —
   * replaces the broken Electron SpeechRecognition/webkitSpeechRecognition.
   * `pcmBuffer` must be an ArrayBuffer of mono Float32 PCM samples at 16kHz
   * (see renderer/widget.js's blobToMono16kPCM). Returns
   * {ok:true, text} or {ok:false, error}. */
  transcribeAudio: (pcmBuffer, languageHint) => ipcRenderer.invoke('audio:transcribe', pcmBuffer, languageHint),

  /** Progress/state pushes during transcribeAudio (model download/load vs.
   * actual inference), so the mic button isn't silent during first-run
   * latency. @param {(status: {state:string, progress?:number, file?:string}) => void} cb */
  onAudioStatus: (cb) => {
    ipcRenderer.on('audio:status', (_event, status) => cb(status));
  },

  /** Command-palette persistence (electron-store, per agent). */
  getCommands: (name) => ipcRenderer.invoke('commands:get', name),
  setCommands: (name, commands) => ipcRenderer.invoke('commands:set', name, commands),

  /** Open a real terminal window (kind "openTerminal" commands). Fire-and-forget. */
  openTerminal: (cwd, command) => ipcRenderer.send('terminal:open', { cwd, command }),

  /** Focus/scope button: proxied backend calls (still AppleScript-based on
   * the backend side, untouched — see CLAUDE.md). */
  focusAgent: (name) => ipcRenderer.invoke('agent:focus', name),
  getAgentTtys: (name) => ipcRenderer.invoke('agent:ttys', name),
  pinTty: (name, tty) => ipcRenderer.invoke('agent:pin-tty', name, tty),

  /** Clear button: types `text` (literally "/clear") into the agent's live
   * linked terminal(s) — same AppleScript-via-iTerm write the Focus button
   * uses to bring a terminal forward, not vortexia messaging. */
  writeToTty: (name, text) => ipcRenderer.invoke('agent:tty-write', name, text),

  /** Door button: mark this agent inactive on the backend and close this
   * widget window. See main.js's agent:deactivate comment. */
  deactivateAgent: (name) => ipcRenderer.invoke('agent:deactivate', name),

  /** "Wake up via vortexia" settings checkbox — backend-synced (not
   * electron-store), same flag `las agent focus`'s wake fallback reads. */
  setWakeEnabled: (name, enabled) => ipcRenderer.invoke('agent:set-wake-enabled', name, enabled),
  getWakeEnabled: (name) => ipcRenderer.invoke('agent:get-wake-enabled', name),
});
