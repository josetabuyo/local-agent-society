'use strict';

/**
 * Renderer logic for one agent widget window. No Node/Electron APIs here —
 * everything comes through the `window.las` bridge exposed by preload.js.
 */

const agentName = window.las.getAgentName() || 'Agent';

const nameEl = document.getElementById('name');
const logEl = document.getElementById('log');
const widgetEl = document.getElementById('widget');
const gearEl = document.getElementById('gear');
const settingsEl = document.getElementById('settings');
const colorEl = document.getElementById('color');
const opacityEl = document.getElementById('opacity');
const alwaysOnTopEl = document.getElementById('alwaysOnTop');
const muteEl = document.getElementById('mute');
const expandWhenHiddenEl = document.getElementById('expandWhenHidden');
const micLanguageEl = document.getElementById('micLanguage');
const closeSettingsEl = document.getElementById('closeSettings');

nameEl.textContent = agentName;
document.title = agentName;

// micLanguage defaults to Spanish, not auto-detect or the agent's TTS
// locale — per explicit request: dictation should assume Spanish unless the
// user picks otherwise, since it's what most agents on this machine are
// dictated to in regardless of what language their own TTS voice speaks.
let prefs = { color: '#90c060', opacity: 0.72, alwaysOnTop: true, mute: false, expandWhenHidden: false, micLanguage: 'es' };
let locale = 'en-US';

function applyPrefsToDom() {
  // Set on the root, not widgetEl: #settings/#commands/#commandEdit/#ttyPicker
  // are siblings of #widget in the DOM (not descendants), so a CSS custom
  // property set on widgetEl's own inline style wouldn't inherit into them —
  // :root is the shared ancestor all of them do inherit from.
  document.documentElement.style.setProperty('--widget-color', prefs.color);
  document.documentElement.style.setProperty('--widget-opacity', String(prefs.opacity));
  colorEl.value = prefs.color;
  opacityEl.value = String(prefs.opacity);
  alwaysOnTopEl.checked = !!prefs.alwaysOnTop;
  muteEl.checked = !!prefs.mute;
  expandWhenHiddenEl.checked = !!prefs.expandWhenHidden;
  micLanguageEl.value = prefs.micLanguage || 'es';
  updateSpeakerIcon();
}

async function init() {
  prefs = await window.las.getPrefs(agentName);
  applyPrefsToDom();
  try {
    const info = await window.las.getAgentInfo(agentName);
    if (info && info.locale) locale = info.locale;
  } catch (err) {
    console.warn('[widget] could not resolve agent locale, defaulting to en-US:', err);
  }
}
init();

// ── settings panel ──────────────────────────────────────────────────────────

gearEl.addEventListener('click', () => {
  settingsEl.classList.remove('hidden');
  window.las.setExpanded(true);
});
closeSettingsEl.addEventListener('click', () => {
  settingsEl.classList.add('hidden');
  window.las.setExpanded(false);
});

async function persist(patch) {
  prefs = await window.las.setPrefs(agentName, patch);
  applyPrefsToDom();
}

colorEl.addEventListener('input', () => persist({ color: colorEl.value }));
opacityEl.addEventListener('input', () => persist({ opacity: Number(opacityEl.value) }));
alwaysOnTopEl.addEventListener('change', () => persist({ alwaysOnTop: alwaysOnTopEl.checked }));
muteEl.addEventListener('change', () => persist({ mute: muteEl.checked }));
expandWhenHiddenEl.addEventListener('change', () => {
  persist({ expandWhenHidden: expandWhenHiddenEl.checked });
  if (!expandWhenHiddenEl.checked) setOcclusionExpanded(false);
});
micLanguageEl.addEventListener('change', () => persist({ micLanguage: micLanguageEl.value }));

// ── expand when hidden (retired Swift "Expand on space change") ────────────
//
// document.visibilitychange on macOS tracks real window occlusion (covered
// by another window, or moved off the active Space) — see main.js's
// window:set-occlusion-expanded comment for why this is the closest
// Electron-only equivalent of the retired NSWindowOcclusionState-based
// mechanism, and why the expanded state is click-through (can never block
// typing into whatever is actually on screen).
//
// Debounced: a brief flicker (e.g. a menu momentarily covering the widget)
// shouldn't trigger a full expand/collapse cycle.

let occlusionExpanded = false;
let visibilityDebounce = null;

function setOcclusionExpanded(expanded) {
  if (expanded === occlusionExpanded) return;
  occlusionExpanded = expanded;
  window.las.setOcclusionExpanded(expanded);
  widgetEl.classList.toggle('occlusion-expanded', expanded);
}

document.addEventListener('visibilitychange', () => {
  if (visibilityDebounce) clearTimeout(visibilityDebounce);
  visibilityDebounce = setTimeout(() => {
    if (!prefs.expandWhenHidden) return;
    setOcclusionExpanded(document.visibilityState === 'hidden');
  }, 400);
});

// ── message log ─────────────────────────────────────────────────────────────

function appendLogEntry(envelope, { speak } = {}) {
  const row = document.createElement('div');
  row.className = 'entry' + (speak ? ' speak' : '');
  const from = document.createElement('span');
  from.className = 'from';
  // A dictated message is a self-send: {from: agentName, to: agentName,
  // source: 'human'} — see main.js's vortexia:send handler. Labeling it with
  // the agent's own name reads as "the agent said this", which is backwards
  // and was confusing in practice: it's the person dictating TO the agent's
  // inbox, not the agent talking to itself.
  const isOwnDictation = envelope.source === 'human' && envelope.from === agentName && envelope.to === agentName;
  from.textContent = isOwnDictation ? '🎤 You' : (envelope.from || '?');
  row.appendChild(from);
  row.appendChild(document.createTextNode(': ' + (envelope.text || '')));
  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;

  // Keep the log from growing unbounded.
  while (logEl.children.length > 100) logEl.removeChild(logEl.firstChild);
}

// ── speech (Web Speech API) ─────────────────────────────────────────────────
//
// Speak-request convention (also documented in main.js): an inbox envelope
// with "kind": "speak" -> { kind: "speak", from, to, text, voice?, ts }.
// This is our own convention for this pass (PROTOCOL.md doesn't define one
// yet); any future vortexia-side convention should update both places.

// speechSynthesis.getVoices() is frequently empty on first call — the OS
// voice list loads asynchronously and fires 'voiceschanged' once ready.
let cachedVoices = [];
function refreshVoices() {
  if (!('speechSynthesis' in window)) return;
  const list = window.speechSynthesis.getVoices();
  if (list.length) cachedVoices = list;
}
if ('speechSynthesis' in window) {
  refreshVoices();
  window.speechSynthesis.addEventListener('voiceschanged', refreshVoices);
}

function speak(text) {
  if (prefs.mute) return;
  if (!('speechSynthesis' in window)) {
    console.warn('[widget] speechSynthesis unavailable in this environment');
    return;
  }
  refreshVoices();
  const utter = new SpeechSynthesisUtterance(text);
  const voices = cachedVoices;
  const { voice, warning } = window.las.pickVoice(agentName, locale, voices);
  if (warning) console.warn('[widget]', warning);
  if (voice) {
    // getVoices() results aren't structured-cloneable 1:1 across the bridge
    // in all Electron versions; re-find by name+lang to be safe.
    const match = voices.find((v) => v.name === voice.name && v.lang === voice.lang);
    if (match) utter.voice = match;
  }
  window.speechSynthesis.speak(utter);
}

window.las.onVortexiaMessage((envelope) => {
  console.log('[widget] received', JSON.stringify(envelope));
  if (envelope && envelope.kind === 'speak') {
    appendLogEntry(envelope, { speak: true });
    speak(envelope.text || '');
  } else if (envelope) {
    appendLogEntry(envelope);
  }
});

window.las.onVortexiaStatus((status) => {
  if (!status.connected) {
    console.warn('[widget] vortexia not connected:', status.error);
  }
});

// ── manual resize (frameless window has no native resize border) ───────────

const resizeHandleEl = document.getElementById('resizeHandle');
let resizing = false;
let lastX = 0;
let lastY = 0;

resizeHandleEl.addEventListener('mousedown', (e) => {
  resizing = true;
  lastX = e.screenX;
  lastY = e.screenY;
  e.preventDefault();
});

window.addEventListener('mousemove', (e) => {
  if (!resizing) return;
  const dw = e.screenX - lastX;
  const dh = e.screenY - lastY;
  lastX = e.screenX;
  lastY = e.screenY;
  window.las.resizeBy(dw, dh);
});

window.addEventListener('mouseup', () => {
  resizing = false;
});

// ── face buttons ─────────────────────────────────────────────────────────
//
// Restores the buttons the retired Swift widget (widget/tray.swift) had on
// its compact face: speaker (mute toggle), mic (dictation), clear (log),
// terminal (command palette), focus/scope (focus + link a TTY). The gear
// button/settings panel above are untouched — this section is purely
// additive.

// -- speaker: one-click mute toggle ------------------------------------------

const speakerEl = document.getElementById('speaker');

function updateSpeakerIcon() {
  speakerEl.innerHTML = prefs.mute ? '&#128263;' : '&#128266;'; // 🔇 / 🔊
  speakerEl.classList.toggle('active', !!prefs.mute);
  speakerEl.title = prefs.mute ? 'Unmute' : 'Mute';
}

speakerEl.addEventListener('click', async () => {
  await persist({ mute: !prefs.mute });
});

// -- clear: type "/clear" into the linked terminal(s) ------------------------
//
// Faithful port of the retired Swift clearSession(), which did
// injectToSession("/clear", source: "raw") — literally typing "/clear" into
// the agent's live iTerm2 session(s). That raw-terminal-write mechanism
// (distinct from the retired inter-agent inject/messaging pipeline — see
// main.js's agent:focus/agent:tty-write comments) still exists on the
// backend and still works; an agent can have more than one linked terminal
// open, so this writes to all of them (backend: POST /agents/{name}/tty-write
// with no `tty` -> _find_all_claude_ttys, not just one selected session).
// Also clears this window's own visible log, which is free and harmless.

document.getElementById('clear').addEventListener('click', async () => {
  logEl.innerHTML = '';
  try {
    const result = await window.las.writeToTty(agentName, '/clear');
    if (!result || !result.written || result.written.length === 0) {
      console.warn('[widget] /clear did not reach any linked terminal:', result);
    }
  } catch (err) {
    console.warn('[widget] tty-write failed:', err);
  }
});

// -- mic: dictation via local, offline Whisper transcription ----------------
//
// Chromium's built-in SpeechRecognition/webkitSpeechRecognition is a cloud
// service tied to a Google API key that only official Chrome builds have —
// verified live, it always fails with error:"network" in Electron even
// though getUserMedia (mic access) works fine, and there is no
// flag/permission fix (see main.js's "audio transcription" section for the
// full writeup). Replacement: this still records with MediaRecorder (same
// getUserMedia mic access, same click-to-start/click-to-stop UX as before),
// but instead of a cloud recognizer it decodes the clip to raw PCM here in
// the renderer (Web Audio API — a browser API, no Node/sandbox issue) and
// hands that PCM to main.js's local Whisper pipeline over IPC. A result is
// published to this agent's OWN vortexia inbox (not typed into a live TTY —
// that mechanism is retired) so the /las-agent skill picks it up at the
// start of this agent's next Claude Code session (see CLAUDE.md) — exactly
// the same destination the old SpeechRecognition.onresult used.

const micEl = document.getElementById('mic');
const MAX_RECORDING_MS = 30000; // safety net if the user forgets to click stop

let mediaRecorder = null;
let recordedChunks = [];
let micState = 'idle'; // 'idle' | 'listening' | 'transcribing'
let maxDurationTimer = null;

function setMicState(next) {
  micState = next;
  micEl.classList.toggle('active', next === 'listening');
  micEl.classList.toggle('busy', next === 'transcribing');
  if (next === 'listening') {
    micEl.title = 'Recording… click to stop';
  } else if (next === 'transcribing') {
    micEl.title = 'Transcribing…';
  } else {
    micEl.title = 'Dictate (click to start/stop)';
  }
}

// Pushed from main.js during transcribeAudio — distinguishes "downloading
// the model, first use only" from ordinary inference so the button doesn't
// just look frozen on the very first dictation on a machine.
window.las.onAudioStatus((status) => {
  if (micState !== 'transcribing' || !status) return;
  if (status.state === 'loading-model') {
    micEl.title = 'Downloading speech model (first use only)…';
  } else if (status.state === 'transcribing') {
    micEl.title = 'Transcribing…';
  }
});

/**
 * Decode a recorded Blob (webm/opus from MediaRecorder) down to mono 16kHz
 * Float32 PCM — the sample format @xenova/transformers' Whisper ASR
 * pipeline expects. An OfflineAudioContext does the resample in one shot
 * instead of a hand-rolled resampler.
 */
async function blobToMono16kPCM(blob) {
  const arrayBuffer = await blob.arrayBuffer();
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  const decodeCtx = new AudioCtx();
  let decoded;
  try {
    decoded = await decodeCtx.decodeAudioData(arrayBuffer);
  } finally {
    decodeCtx.close();
  }
  const targetRate = 16000;
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * targetRate), targetRate);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start(0);
  const rendered = await offline.startRendering();
  return rendered.getChannelData(0);
}

async function stopRecordingAndTranscribe() {
  if (maxDurationTimer) {
    clearTimeout(maxDurationTimer);
    maxDurationTimer = null;
  }
  const recorder = mediaRecorder;
  mediaRecorder = null;
  if (!recorder) return;

  await new Promise((resolve) => {
    if (recorder.state === 'inactive') {
      resolve();
      return;
    }
    recorder.addEventListener('stop', resolve, { once: true });
    recorder.stop();
  });
  recorder.stream.getTracks().forEach((track) => track.stop());

  if (!recordedChunks.length) {
    setMicState('idle');
    return;
  }

  setMicState('transcribing');
  try {
    const blob = new Blob(recordedChunks, { type: recorder.mimeType || 'audio/webm' });
    const pcm = await blobToMono16kPCM(blob);
    // Dictation language is a separate, user-chosen setting (prefs.micLanguage)
    // — NOT derived from the agent's TTS voice locale. An agent can speak
    // back in English (its voice) while the person dictating to it speaks
    // Spanish; coupling the two silently mistranscribed Spanish speech as
    // English whenever an agent's registered voice was English. 'auto' lets
    // Whisper auto-detect (pass no language hint).
    const languageHint = prefs.micLanguage && prefs.micLanguage !== 'auto' ? prefs.micLanguage : null;
    const result = await window.las.transcribeAudio(pcm.buffer, languageHint);
    if (result && result.ok && result.text) {
      // Publish via vortexia — NOT a direct live write into the linked
      // terminal. An earlier pass here did the opposite (writeToTty first,
      // vortexia only as a fallback), faithfully porting the retired Swift
      // injectToSession's live-TTY-write behavior. Reversed on explicit
      // request: direct terminal injection depends on iTerm2/AppleScript
      // specifically and isn't portable across terminal apps (or platforms —
      // Windows has no equivalent at all), which is exactly the class of
      // mechanism this whole project moved away from in favor of vortexia.
      // The Clear button still uses writeToTty on purpose — "/clear" is
      // meant to act on a live session right now, a different use case from
      // dictation, which is fine landing in the inbox for the /las-agent
      // skill to pick up at the next session start (see CLAUDE.md).
      //
      // Don't also appendLogEntry here — this agent is subscribed to its own
      // inbox topic, so the publish loops back through onVortexiaMessage and
      // displays itself; appending it here too would show the line twice.
      const sendResult = await window.las.sendToSelf(agentName, result.text);
      if (!sendResult || !sendResult.ok) {
        console.warn('[widget] mic: failed to publish dictation to own inbox:', sendResult && sendResult.error);
      }
    } else if (result && !result.ok) {
      console.warn('[widget] mic: transcription failed:', result.error);
    }
  } catch (err) {
    console.warn('[widget] mic: transcription pipeline failed:', err);
  } finally {
    setMicState('idle');
  }
}

async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    console.warn('[widget] mic: getUserMedia failed:', err);
    return;
  }
  recordedChunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.addEventListener('dataavailable', (e) => {
    if (e.data && e.data.size) recordedChunks.push(e.data);
  });
  mediaRecorder.start();
  setMicState('listening');
  maxDurationTimer = setTimeout(() => stopRecordingAndTranscribe(), MAX_RECORDING_MS);
}

micEl.addEventListener('click', () => {
  if (micState === 'listening') {
    stopRecordingAndTranscribe();
  } else if (micState === 'idle') {
    startRecording();
  }
  // clicks while 'transcribing' are ignored — nothing meaningful to toggle
});

// -- focus/scope: tap = focus, right-click/long-press = link a TTY ----------
//
// True native OS drag-and-drop (dragging the button onto an arbitrary
// terminal window, as the Swift ScopeDragButton did via NSDraggingSource +
// a pasteboard string) is out of scope for this pass — see report. This
// implements the task's documented fallback instead: a press-and-hold (or
// right-click) opens a small picker of this agent's candidate TTYs
// (GET /agents/{name}/ttys), and picking one calls POST
// /agents/{name}/pin-tty to link it, matching what a completed drag would
// have done on the backend side.

const focusEl = document.getElementById('focus');
const ttyPickerEl = document.getElementById('ttyPicker');
const ttyListEl = document.getElementById('ttyList');
const closeTtyPickerEl = document.getElementById('closeTtyPicker');

focusEl.addEventListener('click', async () => {
  try {
    await window.las.focusAgent(agentName);
  } catch (err) {
    console.warn('[widget] focus: request failed:', err);
  }
});

let longPressTimer = null;
focusEl.addEventListener('mousedown', () => {
  longPressTimer = setTimeout(() => openTtyPicker(), 600);
});
focusEl.addEventListener('mouseup', () => {
  if (longPressTimer) clearTimeout(longPressTimer);
});
focusEl.addEventListener('mouseleave', () => {
  if (longPressTimer) clearTimeout(longPressTimer);
});
focusEl.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  openTtyPicker();
});

async function openTtyPicker() {
  ttyListEl.innerHTML = '<div class="command-row">Loading…</div>';
  ttyPickerEl.classList.remove('hidden');
  window.las.setExpanded(true);
  let result;
  try {
    result = await window.las.getAgentTtys(agentName);
  } catch (err) {
    ttyListEl.innerHTML = `<div class="command-row">Error: ${String(err)}</div>`;
    return;
  }
  const ttys = (result && result.ttys) || [];
  if (!ttys.length) {
    ttyListEl.innerHTML = '<div class="command-row">No candidate TTYs found for this agent.</div>';
    return;
  }
  ttyListEl.innerHTML = '';
  for (const tty of ttys) {
    const row = document.createElement('div');
    row.className = 'command-row';
    const label = document.createElement('span');
    label.className = 'command-label';
    label.textContent = tty;
    row.appendChild(label);
    const pinBtn = document.createElement('button');
    pinBtn.textContent = 'Link';
    pinBtn.addEventListener('click', async () => {
      await window.las.pinTty(agentName, tty);
      ttyPickerEl.classList.add('hidden');
      window.las.setExpanded(false);
    });
    row.appendChild(pinBtn);
    ttyListEl.appendChild(row);
  }
}

closeTtyPickerEl.addEventListener('click', () => {
  ttyPickerEl.classList.add('hidden');
  window.las.setExpanded(false);
});

// -- terminal: command palette ------------------------------------------------

const terminalEl = document.getElementById('terminal');
const commandsEl = document.getElementById('commands');
const commandsListEl = document.getElementById('commandsList');
const commandsAddEl = document.getElementById('commandsAdd');
const closeCommandsEl = document.getElementById('closeCommands');

const commandEditEl = document.getElementById('commandEdit');
const cmdLabelEl = document.getElementById('cmdLabel');
const cmdKindEl = document.getElementById('cmdKind');
const cmdCwdRowEl = document.getElementById('cmdCwdRow');
const cmdCommandRowEl = document.getElementById('cmdCommandRow');
const cmdTextRowEl = document.getElementById('cmdTextRow');
const cmdCwdEl = document.getElementById('cmdCwd');
const cmdCommandEl = document.getElementById('cmdCommand');
const cmdTextEl = document.getElementById('cmdText');
const cmdSaveEl = document.getElementById('cmdSave');
const cmdCancelEl = document.getElementById('cmdCancel');

let editingIndex = null; // null => adding a new command

terminalEl.addEventListener('click', async () => {
  if (!commandsEl.classList.contains('hidden')) {
    commandsEl.classList.add('hidden');
    window.las.setExpanded(false);
    return;
  }
  await renderCommandsList();
  commandsEl.classList.remove('hidden');
  window.las.setExpanded(true);
});

closeCommandsEl.addEventListener('click', () => {
  commandsEl.classList.add('hidden');
  window.las.setExpanded(false);
});

async function renderCommandsList() {
  const commands = await window.las.getCommands(agentName);
  commandsListEl.innerHTML = '';
  if (!commands.length) {
    commandsListEl.innerHTML = '<div class="command-row">No saved commands yet.</div>';
  }
  commands.forEach((cmd, index) => {
    const row = document.createElement('div');
    row.className = 'command-row';

    const kindTag = document.createElement('span');
    kindTag.className = 'command-kind';
    kindTag.textContent = cmd.kind === 'sendMessage' ? 'MSG' : 'TERM';
    row.appendChild(kindTag);

    const label = document.createElement('span');
    label.className = 'command-label';
    label.textContent = cmd.label || '(untitled)';
    label.title = 'Run';
    label.addEventListener('click', () => runCommand(cmd));
    row.appendChild(label);

    const editBtn = document.createElement('button');
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => openCommandEdit(cmd, index));
    row.appendChild(editBtn);

    const delBtn = document.createElement('button');
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', async () => {
      const next = commands.slice();
      next.splice(index, 1);
      await window.las.setCommands(agentName, next);
      await renderCommandsList();
    });
    row.appendChild(delBtn);

    commandsListEl.appendChild(row);
  });
}

function runCommand(cmd) {
  commandsEl.classList.add('hidden');
  window.las.setExpanded(false);
  if (cmd.kind === 'sendMessage') {
    window.las.vortexiaSend(agentName, cmd.text || '');
  } else {
    window.las.openTerminal(cmd.cwd || '', cmd.command || '');
  }
}

function updateCommandEditRows() {
  const isTerminal = cmdKindEl.value === 'openTerminal';
  cmdCwdRowEl.style.display = isTerminal ? 'flex' : 'none';
  cmdCommandRowEl.style.display = isTerminal ? 'flex' : 'none';
  cmdTextRowEl.style.display = isTerminal ? 'none' : 'flex';
}

cmdKindEl.addEventListener('change', updateCommandEditRows);

function openCommandEdit(cmd, index) {
  editingIndex = typeof index === 'number' ? index : null;
  cmdLabelEl.value = cmd ? cmd.label || '' : '';
  cmdKindEl.value = cmd ? cmd.kind : 'openTerminal';
  cmdCwdEl.value = cmd ? cmd.cwd || '' : '';
  cmdCommandEl.value = cmd ? cmd.command || '' : '';
  cmdTextEl.value = cmd ? cmd.text || '' : '';
  updateCommandEditRows();
  commandsEl.classList.add('hidden');
  commandEditEl.classList.remove('hidden');
}

commandsAddEl.addEventListener('click', () => openCommandEdit(null, null));
cmdCancelEl.addEventListener('click', () => {
  commandEditEl.classList.add('hidden');
  commandsEl.classList.remove('hidden');
});

cmdSaveEl.addEventListener('click', async () => {
  const kind = cmdKindEl.value === 'sendMessage' ? 'sendMessage' : 'openTerminal';
  const label = cmdLabelEl.value.trim() || (kind === 'sendMessage' ? (cmdTextEl.value.trim() || 'message') : (cmdCommandEl.value.trim() || 'terminal'));
  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    label,
    kind,
    cwd: cmdCwdEl.value.trim(),
    command: cmdCommandEl.value.trim(),
    text: cmdTextEl.value.trim(),
  };
  const commands = await window.las.getCommands(agentName);
  if (editingIndex === null) {
    commands.push(entry);
  } else {
    entry.id = commands[editingIndex].id;
    commands[editingIndex] = entry;
  }
  await window.las.setCommands(agentName, commands);
  commandEditEl.classList.add('hidden');
  commandsEl.classList.remove('hidden');
  await renderCommandsList();
});
