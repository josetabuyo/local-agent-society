'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

function readSrc(...parts) {
  return fs.readFileSync(path.join(ROOT, ...parts), 'utf8');
}

/**
 * Strip //, /* *\/ comments and string literals are NOT stripped (we still
 * want to catch actual "osascript" calls inside strings) — this only removes
 * comment text so explanatory prose ("we deliberately avoid AppleScript")
 * doesn't trip source-scanning assertions.
 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^[ \t]*\/\/.*$/gm, '');
}

function extractFunctionBody(src, needle) {
  const start = src.indexOf(needle);
  assert.notEqual(start, -1, `could not find "${needle}"`);
  let depth = 0;
  let bodyStart = -1;
  for (let i = start; i < src.length; i++) {
    const ch = src[i];
    if (ch === '{') {
      if (depth === 0) bodyStart = i;
      depth++;
    } else if (ch === '}') {
      depth--;
      if (depth === 0) return src.slice(bodyStart, i + 1);
    }
  }
  throw new Error(`unbalanced braces after "${needle}"`);
}

// ── single-instance lock ────────────────────────────────────────────────────

test('main.js requests the single-instance lock', () => {
  const src = readSrc('main.js');
  assert.match(src, /requestSingleInstanceLock\(\)/);
  assert.match(src, /app\.quit\(\)/, 'must quit when the lock is not obtained');
});

// ── reopen destroys-and-recreates ───────────────────────────────────────────

test('reopenWidget destroys the existing window before creating a new one', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function reopenWidget(name)');
  const destroyPos = body.indexOf('.destroy()');
  const createPos = body.indexOf('createWidgetWindow(name)');
  assert.notEqual(destroyPos, -1, 'reopenWidget must call .destroy() on the existing window');
  assert.notEqual(createPos, -1, 'reopenWidget must call createWidgetWindow(name)');
  assert.ok(
    destroyPos < createPos,
    'destroy() must happen before createWidgetWindow so the old window is gone before the new one is made (matches the Swift reopen-not-focus fix)'
  );
});

test('openWidget does NOT destroy an existing window (that would defeat single-instance dedup)', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function openWidget(name)');
  assert.doesNotMatch(body, /\.destroy\(\)/);
});

test('main.js claims the real localagentsociety:// scheme (post-cutover)', () => {
  const src = readSrc('main.js');
  const code = stripComments(src);
  assert.match(code, /PROTOCOL_SCHEME\s*=\s*['"`]localagentsociety['"`]/,
    'PROTOCOL_SCHEME must be the real scheme, not the pre-cutover -dev suffixed one');
  const devSchemeUsages = [...code.matchAll(/['"`]localagentsociety-dev['"`]/g)];
  assert.equal(devSchemeUsages.length, 0,
    'no code should reference the pre-cutover localagentsociety-dev scheme anymore');
});

// ── no IN-PROCESS Apple Events; spawned `osascript` is fine ─────────────────
//
// The historical incident this guards against was the retired Swift tray
// binary's IN-PROCESS NSAppleEventDescriptor calls losing their Apple Events
// TCC grant on every recompile (a code-signing identity problem specific to
// a compiled, frequently-rebuilt app bundle). Spawning the `osascript` CLI
// as a child process is a different mechanism: macOS attributes the
// automation permission to the stable `osascript` binary itself, not to
// this app, so rebuilding widget-electron never affects it — the backend
// (backend/main.py) has safely done exactly this all along for focus/
// terminal. So: ban NSAppleEventDescriptor (in-process) everywhere, and ban
// spawning `osascript` everywhere EXCEPT openTerminalAtPath's macOS branch
// in main.js, which is the one legitimate, reviewed use (opening iTerm2 for
// the command-palette's "openTerminal" commands).

test('no in-process Apple Events anywhere in the app source', () => {
  const dirs = ['.', 'renderer', 'lib'];
  const offenders = [];
  for (const dir of dirs) {
    const abs = path.join(ROOT, dir);
    for (const entry of fs.readdirSync(abs)) {
      if (!/\.(js|html|css)$/.test(entry)) continue;
      const full = path.join(abs, entry);
      const content = stripComments(fs.readFileSync(full, 'utf8'));
      if (/NSAppleEventDescriptor/i.test(content)) {
        offenders.push(path.relative(ROOT, full));
      }
    }
  }
  assert.deepEqual(offenders, [], `found in-process Apple Events usage in: ${offenders.join(', ')}`);
});

test('osascript is only spawned from openTerminalAtPath (macOS iTerm2 launch), nowhere else', () => {
  const dirs = ['.', 'renderer', 'lib'];
  const offenders = [];
  for (const dir of dirs) {
    const abs = path.join(ROOT, dir);
    for (const entry of fs.readdirSync(abs)) {
      if (!/\.(js|html|css)$/.test(entry)) continue;
      const full = path.join(abs, entry);
      if (full === path.join(ROOT, 'main.js')) continue; // checked separately below
      const content = stripComments(fs.readFileSync(full, 'utf8'));
      if (/osascript|AppleScript/i.test(content)) {
        offenders.push(path.relative(ROOT, full));
      }
    }
  }
  assert.deepEqual(offenders, [], `found unexpected osascript/AppleScript references in: ${offenders.join(', ')}`);

  const mainSrc = readSrc('main.js');
  const occurrences = [...stripComments(mainSrc).matchAll(/osascript/gi)];
  assert.ok(occurrences.length > 0, 'expected openTerminalAtPath to spawn osascript for iTerm2');
  const body = extractFunctionBody(mainSrc, 'function openTerminalAtPath(cwd, command)');
  for (const m of stripComments(body).matchAll(/osascript/gi)) {
    void m; // presence check only — every osascript reference in main.js must be inside this function
  }
  const outsideCount = occurrences.length - [...stripComments(body).matchAll(/osascript/gi)].length;
  assert.equal(outsideCount, 0, 'osascript must only be spawned inside openTerminalAtPath');
});

// ── voice-selection hashing ──────────────────────────────────────────────────

const { hashString, hashIndex, pickVoice } = require('../lib/voiceHash');

test('hashString is a pure deterministic function of its input', () => {
  assert.equal(hashString('Alpha'), hashString('Alpha'));
  assert.notEqual(hashString('Alpha'), hashString('Beta'));
});

test('pickVoice is deterministic for a given agent name + locale + voice list', () => {
  const voices = [
    { name: 'V1', lang: 'en-US' },
    { name: 'V2', lang: 'en-GB' },
    { name: 'V3', lang: 'es-MX' },
  ];
  const a = pickVoice('AgentSmith', 'en-US', voices);
  const b = pickVoice('AgentSmith', 'en-US', voices);
  assert.deepEqual(a, b);
  assert.notEqual(a.voice, null);
  assert.match(a.voice.lang, /^en/);
});

test('pickVoice filters by language prefix, ignoring region', () => {
  const voices = [
    { name: 'EnUS', lang: 'en-US' },
    { name: 'EsMX', lang: 'es-MX' },
    { name: 'EsES', lang: 'es-ES' },
  ];
  const { voice } = pickVoice('Bot', 'es-ES', voices);
  assert.match(voice.lang, /^es/);
});

test('pickVoice falls back gracefully with a warning when no voice matches the locale', () => {
  const voices = [{ name: 'OnlyFrench', lang: 'fr-FR' }];
  const { voice, warning } = pickVoice('Bot', 'en-US', voices);
  assert.notEqual(voice, null);
  assert.match(warning, /falling back/i);
});

test('pickVoice handles an empty voice list without throwing', () => {
  const { voice, warning } = pickVoice('Bot', 'en-US', []);
  assert.equal(voice, null);
  assert.match(warning, /no voices/i);
});

test('hashIndex is stable across repeated calls and within bounds', () => {
  const list = ['a', 'b', 'c', 'd'];
  const idx = hashIndex('SomeAgentName', list);
  assert.equal(idx, hashIndex('SomeAgentName', list));
  assert.ok(idx >= 0 && idx < list.length);
});

// ── widget/ (Swift) retired ──────────────────────────────────────────────────
// The native Swift widget was deleted after this Electron app reached full
// parity with `las start`/`las widget`/`las stop` (see swift-widget-final git
// tag for the retired source, if it's ever needed again).

test('widget/ (Swift) has been removed — this Electron app is the sole widget', () => {
  const swiftDir = path.join(ROOT, '..', 'widget');
  assert.ok(!fs.existsSync(swiftDir));
});

// ── face buttons (restored from widget/tray.swift) ──────────────────────────

test('index.html renders all 6 face buttons (gear + 5 restored ones)', () => {
  const html = readSrc('renderer', 'index.html');
  for (const id of ['gear', 'clear', 'terminal', 'speaker', 'mic', 'focus']) {
    assert.match(html, new RegExp(`id="${id}"`), `missing button #${id}`);
  }
});

test('preload.js exposes the face-button bridge methods on window.las', () => {
  const src = readSrc('preload.js');
  for (const method of [
    'getAgentInfo',
    'vortexiaSend',
    'sendToSelf',
    'getCommands',
    'setCommands',
    'openTerminal',
    'focusAgent',
    'getAgentTtys',
    'pinTty',
  ]) {
    assert.match(src, new RegExp(`${method}\\s*:`), `preload.js missing window.las.${method}`);
  }
});

test('speaker button toggles the existing mute pref (no new pref key)', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, "speakerEl.addEventListener('click', async () => {");
  assert.match(body, /persist\(\s*\{\s*mute:\s*!prefs\.mute\s*\}\s*\)/);
});

test('mic dictation publishes via vortexia (sendToSelf), not a direct live write into the linked terminal', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, 'async function stopRecordingAndTranscribe()');
  assert.match(body, /window\.las\.sendToSelf\(agentName,\s*result\.text\)/,
    'mic result must be sent via sendToSelf — direct terminal injection (writeToTty) is iTerm2/AppleScript-specific and not portable, explicitly rejected for dictation in favor of vortexia');
  assert.doesNotMatch(body, /window\.las\.writeToTty/,
    'mic must NOT use writeToTty — that stays reserved for the Clear button\'s "/clear", a different use case (act on a live session now vs. queue for next session start)');
});

test('mic dictation does not double-log: sendToSelf loops back via the agent\'s own vortexia subscription instead of appending locally', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, 'async function stopRecordingAndTranscribe()');
  assert.doesNotMatch(body, /appendLogEntry\(/,
    'must not appendLogEntry directly here — sendToSelf publishes to this agent\'s own inbox topic, which this widget is also subscribed to, so the message loops back through onVortexiaMessage and displays itself; appending it here too would double it');
});

// ── mic dictation: local Whisper transcription (replaces the broken ────────
// Electron SpeechRecognition/webkitSpeechRecognition — see main.js's "audio
// transcription" section and widget.js's mic section for the full writeup.
// webkitSpeechRecognition is a cloud API tied to a Google key only official
// Chrome builds have; it cannot work in Electron under any configuration.

test('mic dictation no longer USES the broken SpeechRecognition/webkitSpeechRecognition API (comments explaining why it was replaced are fine)', () => {
  const src = stripComments(readSrc('renderer', 'widget.js'));
  assert.doesNotMatch(src, /webkitSpeechRecognition|window\.SpeechRecognition\b/,
    'SpeechRecognition has no working backend in Electron and must not be used');
});

test('main.js exposes a local Whisper transcription IPC handler (audio:transcribe)', () => {
  const src = readSrc('main.js');
  assert.match(src, /ipcMain\.handle\('audio:transcribe'/);
  assert.match(src, /@xenova\/transformers/, 'expected the local Whisper library to be imported');
  assert.match(src, /automatic-speech-recognition/, 'expected the ASR pipeline task name');
});

test('preload.js bridges transcribeAudio and onAudioStatus for the mic\'s local-Whisper pipeline', () => {
  const src = readSrc('preload.js');
  assert.match(src, /transcribeAudio\s*:/);
  assert.match(src, /onAudioStatus\s*:/);
});

test('mic recording uses MediaRecorder (still real getUserMedia audio capture, only transcription moved local)', () => {
  const src = readSrc('renderer', 'widget.js');
  assert.match(src, /getUserMedia\(/);
  assert.match(src, /new MediaRecorder\(/);
});

test('mic sends recorded audio to transcribeAudio and routes text through the same sendToSelf pipeline as before', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, 'async function stopRecordingAndTranscribe()');
  assert.match(body, /window\.las\.transcribeAudio\(/);
  assert.match(body, /result\.ok\s*&&\s*result\.text/);
});

test('mic button has a distinct busy/transcribing visual state, separate from the recording (active) state', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, "function setMicState(next) {");
  assert.match(body, /classList\.toggle\('active',\s*next === 'listening'\)/);
  assert.match(body, /classList\.toggle\('busy',\s*next === 'transcribing'\)/);
});

test('mic recording has a max-duration safety net so a forgotten click-to-stop does not record forever', () => {
  const src = readSrc('renderer', 'widget.js');
  assert.match(src, /MAX_RECORDING_MS/);
  assert.match(src, /setTimeout\(\(\)\s*=>\s*stopRecordingAndTranscribe\(\),\s*MAX_RECORDING_MS\)/);
});

test('main.js vortexia:send handler resolves the sending agent from the window map (reuses the existing per-window VortexiaClient)', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, "ipcMain.handle('vortexia:send', async (event, toName, text) => {");
  assert.match(body, /nameForWindow\(win\)/);
  assert.match(body, /vortexiaClients\.get\(fromName\)/);
});

test('main.js never opens a second vortexia connection for face-button sends (no new VortexiaClient construction outside connectVortexia)', () => {
  const src = readSrc('main.js');
  const matches = [...src.matchAll(/new VortexiaClient\(/g)];
  assert.equal(matches.length, 1, 'expected exactly one `new VortexiaClient(` call site (inside connectVortexia)');
});

test('command palette persistence: shape has {id, label, kind, cwd, command, text} and is stored per-agent under commands.<agentName>', () => {
  const mainSrc = readSrc('main.js');
  assert.match(mainSrc, /store\.get\(`commands\.\$\{name\}`/);
  assert.match(mainSrc, /store\.set\(`commands\.\$\{name\}`/);

  const rendererSrc = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(rendererSrc, "cmdSaveEl.addEventListener('click', async () => {");
  for (const field of ['id:', 'label,', 'kind,', 'cwd:', 'command:', 'text:']) {
    assert.ok(body.includes(field), `saved command entry missing field matching "${field}"`);
  }
});

test('command palette "sendMessage" kind runs via vortexiaSend, "openTerminal" kind runs via openTerminal', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, 'function runCommand(cmd)');
  assert.match(body, /cmd\.kind === 'sendMessage'/);
  assert.match(body, /window\.las\.vortexiaSend\(agentName,\s*cmd\.text/);
  assert.match(body, /window\.las\.openTerminal\(cmd\.cwd/);
});

test('openTerminalAtPath opens iTerm2 (this project\'s default terminal) via spawned osascript on macOS, not Terminal.app', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function openTerminalAtPath(cwd, command) {');
  assert.match(body, /osascript/i, 'expected a spawned osascript call to open iTerm2');
  assert.match(body, /iTerm2/, 'expected iTerm2, not Terminal.app — see main.js header comment for why');
  assert.doesNotMatch(body, /-a['"`],?\s*['"`]Terminal['"`]/, 'must not fall back to Terminal.app');
});

test('focus button click calls focusAgent(agentName); a separate contextmenu/long-press opens the TTY picker (documented simplified route, not native drag)', () => {
  const src = readSrc('renderer', 'widget.js');
  const clickBody = extractFunctionBody(src, "focusEl.addEventListener('click', async () => {");
  assert.match(clickBody, /window\.las\.focusAgent\(agentName\)/);
  assert.match(src, /openTtyPicker/, 'expected a TTY-picker fallback for linking, since true native drag-and-drop is out of scope for this pass');
});

test('TTY picker links via pinTty(agentName, tty), matching the backend pin-tty body shape {tty}', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, 'async function openTtyPicker() {');
  assert.match(body, /window\.las\.getAgentTtys\(agentName\)/);
  const fullSrc = readSrc('renderer', 'widget.js');
  assert.match(fullSrc, /window\.las\.pinTty\(agentName,\s*tty\)/);
});

// ── auto-expand for overlay panels (settings/commands/TTY picker) ──────────

test('main.js exposes an idempotent window:set-expanded handler that remembers collapsed bounds', () => {
  const src = readSrc('main.js');
  assert.match(src, /ipcMain\.on\('window:set-expanded'/);
  assert.match(src, /collapsedBounds/);
  assert.match(src, /expandedWindows/);
});

test('preload.js exposes setExpanded on window.las', () => {
  const src = readSrc('preload.js');
  assert.match(src, /setExpanded\s*:/);
});

test('gear button expands the window on open and collapses it on close', () => {
  const src = readSrc('renderer', 'widget.js');
  const openBody = extractFunctionBody(src, "gearEl.addEventListener('click', () => {");
  assert.match(openBody, /window\.las\.setExpanded\(true\)/);
  const closeBody = extractFunctionBody(src, "closeSettingsEl.addEventListener('click', () => {");
  assert.match(closeBody, /window\.las\.setExpanded\(false\)/);
});

test('every panel that calls setExpanded(true) has a corresponding path back to setExpanded(false)', () => {
  const src = readSrc('renderer', 'widget.js');
  const trueCount = [...src.matchAll(/setExpanded\(true\)/g)].length;
  const falseCount = [...src.matchAll(/setExpanded\(false\)/g)].length;
  assert.ok(trueCount > 0 && falseCount > 0, 'expected both expand and collapse call sites');
});

// ── expand when hidden (retired Swift "Expand on space change") ────────────

test('main.js exposes window:set-occlusion-expanded, defers to panel-expand, and makes the window click-through', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, "ipcMain.on('window:set-occlusion-expanded', (event, expanded) => {");
  assert.match(body, /expandedWindows\.has\(win\)/, 'must not fight with the settings/commands panel auto-expand');
  assert.match(body, /setIgnoreMouseEvents\(true/, 'expanded state must be click-through, per the design constraint that it can never block typing');
  assert.match(body, /setIgnoreMouseEvents\(false\)/, 'must restore normal mouse handling on collapse');
});

test('expandWhenHidden defaults to false, matching the retired Prefs.expandOnSpaceChange default', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'const DEFAULT_PREFS = {');
  assert.match(body, /expandWhenHidden:\s*false/);
});

test('visibilitychange handler is debounced and gated by the expandWhenHidden pref', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, "document.addEventListener('visibilitychange', () => {");
  assert.match(body, /setTimeout/, 'expected a debounce so brief occlusion flickers do not trigger a resize cycle');
  assert.match(body, /prefs\.expandWhenHidden/);
});

// ── dictation language is a user setting, independent of the agent's TTS voice ─

test('micLanguage defaults to Spanish and is NOT derived from the agent\'s TTS voice locale', () => {
  const mainSrc = readSrc('main.js');
  const body = extractFunctionBody(mainSrc, 'const DEFAULT_PREFS = {');
  assert.match(body, /micLanguage:\s*['"`]es['"`]/);

  const widgetSrc = readSrc('renderer', 'widget.js');
  assert.match(widgetSrc, /prefs\.micLanguage/, 'expected the mic pipeline to read prefs.micLanguage');
  assert.doesNotMatch(
    widgetSrc,
    /languageHint\s*=\s*\(locale/,
    'dictation language must not be derived from the agent\'s TTS locale — an agent can speak English while being dictated to in Spanish'
  );
});

test('index.html exposes a dictation-language picker defaulting to Spanish', () => {
  const html = readSrc('renderer', 'index.html');
  assert.match(html, /id="micLanguage"/);
  assert.match(html, /<option value="es">/);
});

test('own dictation (self-send: from===to===agentName, source==="human") is labeled as the user, not the agent\'s own name', () => {
  // Not using extractFunctionBody here: appendLogEntry's own signature
  // contains braces in its destructured param ({ speak } = {}), which
  // confuses that helper's brace-balancing (it'd stop at the param's `{}`,
  // never reaching the real function body). Simple substring checks instead.
  const src = readSrc('renderer', 'widget.js');
  const appendLogEntryIdx = src.indexOf('function appendLogEntry(envelope, { speak } = {}) {');
  assert.notEqual(appendLogEntryIdx, -1, 'could not find appendLogEntry');
  const nextFnIdx = src.indexOf('\nfunction ', appendLogEntryIdx + 1);
  const body = src.slice(appendLogEntryIdx, nextFnIdx === -1 ? undefined : nextFnIdx);
  assert.match(body, /isOwnDictation/);
  assert.match(body, /source\s*===\s*['"`]human['"`]/);
});

// ── all face buttons in one bottom row (gear moved down on request) ────────

test('gear button lives inside .buttonbar, not floating separately at the top', () => {
  const html = readSrc('renderer', 'index.html');
  const barIdx = html.indexOf('class="buttonbar"');
  assert.notEqual(barIdx, -1, 'could not find .buttonbar');
  const barEndIdx = html.indexOf('</div>\n\n', barIdx); // buttonbar's closing div
  const barSection = html.slice(barIdx, barEndIdx === -1 ? undefined : barEndIdx);
  assert.match(barSection, /id="gear"/, 'gear button must be inside .buttonbar');
});

test('no CSS rule positions a face button absolutely at the top (all six sit in the bottom flex row)', () => {
  const css = readSrc('renderer', 'widget.css');
  assert.doesNotMatch(css, /^\.gear\s*\{/m, '.gear should no longer exist as a standalone top-positioned rule');
});

// ── backgroundThrottling:false so "expand when hidden" actually paints ─────

test('backgroundThrottling is NOT disabled unconditionally at window creation — it must stay on by default so occlusion detection keeps working', () => {
  // Confirmed live, twice: `backgroundThrottling: false` set unconditionally
  // in the BrowserWindow constructor DOES let a resize while occluded
  // actually paint — but it also stops document.visibilitychange from ever
  // firing 'hidden' at all (zero events across a real Space switch), since
  // Chromium's occlusion-based throttling and Page Visibility reporting
  // share the same underlying signal. Detection must stay on by default;
  // see the next test for the correct dynamic approach.
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function createWidgetWindow(name) {');
  assert.doesNotMatch(body, /webPreferences:\s*\{[^}]*backgroundThrottling:\s*false/s);
});

test('window:set-occlusion-expanded toggles backgroundThrottling dynamically: off only once already expanded, back on when collapsing', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, "ipcMain.on('window:set-occlusion-expanded', (event, expanded) => {");
  const offIdx = body.indexOf('setBackgroundThrottling(false)');
  const onIdx = body.indexOf('setBackgroundThrottling(true)');
  assert.notEqual(offIdx, -1, 'expected setBackgroundThrottling(false) once occlusion is already detected, so the fullscreen banner actually paints while off-Space');
  assert.notEqual(onIdx, -1, 'expected setBackgroundThrottling(true) on collapse, restoring normal detection for the next cycle');
});
