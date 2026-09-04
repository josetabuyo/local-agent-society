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
  const createPos = body.indexOf('createWidgetWindow(name');
  assert.notEqual(destroyPos, -1, 'reopenWidget must call .destroy() on the existing window');
  assert.notEqual(createPos, -1, 'reopenWidget must call createWidgetWindow(name, ...)');
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
  assert.match(src, /maxDurationTimer = setTimeout\(\(\) => \{[\s\S]*?stopRecordingAndTranscribe\(\);[\s\S]*?\}, MAX_RECORDING_MS\);/);
});

test('mic recording schedules countdown beeps (10s/5s/2s) before the max-duration cutoff, cleared on manual stop', () => {
  const src = readSrc('renderer', 'widget.js');
  assert.match(src, /scheduleCountdownBeeps/);
  assert.match(src, /MAX_RECORDING_MS - 10000/);
  assert.match(src, /MAX_RECORDING_MS - 5000/);
  assert.match(src, /MAX_RECORDING_MS - 2000/);
  const stopBody = extractFunctionBody(src, 'async function stopRecordingAndTranscribe() {');
  assert.match(stopBody, /clearCountdownTimers\(\)/);
});

test('double-clicking the mic runs a self-test (not a real recording) and shows a floating toast', () => {
  const src = readSrc('renderer', 'widget.js');
  assert.match(src, /micEl\.addEventListener\('dblclick', \(\) => \{/);
  const testBody = extractFunctionBody(src, 'async function runMicSelfTest() {');
  assert.match(testBody, /getUserMedia/);
  assert.match(testBody, /showMicToast/);
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

test('gear button toggles settings mode, which expands the window open and shrinks it back closed', () => {
  const src = readSrc('renderer', 'widget.js');
  assert.match(src, /gearEl\.addEventListener\('click',\s*\(\)\s*=>\s*setSettingsOpen\(!settingsOpen\)\)/);
  const body = extractFunctionBody(src, 'function setSettingsOpen(open) {');
  assert.match(body, /window\.las\.setExpanded\(open,\s*SETTINGS_HEIGHT\)/, 'must pass open through, covering both the expand and the shrink-back-closed path');
  assert.match(body, /gearEl\.classList\.toggle\('active', open\)/, "gear must visually show 'pressed' while settings is open");
});

test('every panel that calls setExpanded(true, ...) has a corresponding path back to setExpanded(false)', () => {
  const src = readSrc('renderer', 'widget.js');
  const trueCount = [...src.matchAll(/setExpanded\(true\b/g)].length;
  const falseCount = [...src.matchAll(/setExpanded\(false\)/g)].length;
  assert.ok(trueCount > 0 && falseCount > 0, 'expected both expand and collapse call sites');
});

test('window:set-expanded accepts an optional height override, falling back to EXPANDED_HEIGHT', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, "ipcMain.on('window:set-expanded', (event, expanded, height) => {");
  assert.match(body, /height\s*\|\|\s*EXPANDED_HEIGHT/);
});

// ── expand when hidden (retired Swift "Expand on space change") ────────────

test('main.js exposes window:set-occlusion-expanded, defers to panel-expand, and makes the window click-through', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, "ipcMain.on('window:set-occlusion-expanded', (event, expanded) => {");
  assert.match(body, /expandedWindows\.has\(win\)/, 'must not fight with the settings/commands panel auto-expand');
  assert.match(body, /setIgnoreMouseEvents\(true/, 'expanded state must be click-through, per the design constraint that it can never block typing');
  assert.match(body, /setIgnoreMouseEvents\(false\)/, 'must restore normal mouse handling on collapse');
});

test('expandWhenHidden defaults to true, per explicit request (was off by default, matching the retired Prefs.expandOnSpaceChange default, until changed)', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'const DEFAULT_PREFS = {');
  assert.match(body, /expandWhenHidden:\s*true/);
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
  const start = src.indexOf('function createWidgetWindow(name');
  assert.notEqual(start, -1, 'could not find createWidgetWindow');
  const end = src.indexOf('\nfunction ', start + 1);
  const body = src.slice(start, end === -1 ? undefined : end);
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

// ── mosaic tiling for multiple occlusion-expanded widgets on one display ───
// Ported from the retired Swift widget's AppDelegate.mosaicTiles/
// applyMosaicLayout (swift-widget-final tag, tray.swift) — without this,
// several widgets going occlusion-expanded on the same screen at once just
// stack exactly on top of each other instead of tiling.

test('window:set-occlusion-expanded schedules a mosaic re-layout on expand (not a direct full-workArea setBounds), but NOT on collapse', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, "ipcMain.on('window:set-occlusion-expanded', (event, expanded) => {");
  const collapseIdx = body.indexOf('} else if');
  const expandBranch = body.slice(0, collapseIdx);
  const collapseBranch = body.slice(collapseIdx);
  assert.match(expandBranch, /scheduleMosaicLayout\(/, 'expand branch must schedule a mosaic layout instead of unconditionally filling the whole display');
  assert.doesNotMatch(
    collapseBranch,
    /scheduleMosaicLayout\(/,
    'collapse must NOT re-tile remaining siblings — that produced a visible two-step animation (jump to a bigger tile, then immediately collapse); survivors keep their tile until they too restore'
  );
});

test('mosaic grouping key is (display, macOS Space), not display alone — every widget on the machine sharing one physical display must not be lumped into a single giant grid', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function mosaicKeyFor(win) {');
  assert.match(body, /spaces\.getSpaceForWindow\(win\)/);
  assert.match(body, /`\$\{displayId\}:\$\{spaceId/, 'key must combine displayId with spaceId, not displayId alone');
});

test('mosaicTiles returns the full work area for 0 or 1 windows, and non-overlapping tiles otherwise', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function mosaicTiles(count, workArea) {');
  const fn = new Function(`function mosaicTiles(count, workArea) ${body} return mosaicTiles;`)();
  const area = { x: 0, y: 0, width: 1000, height: 800 };

  assert.deepEqual(fn(0, area), []);
  assert.deepEqual(fn(1, area), [{ x: 0, y: 0, width: 1000, height: 800 }]);

  // 2, 3, and even counts >=4 (full 2xN grid) cover the work area exactly;
  // an odd count >=4 (e.g. 5 = 2 cols x 3 rows) leaves one grid cell empty,
  // same as the ported Swift layout.
  for (const count of [2, 3, 4, 5, 6]) {
    const tiles = fn(count, area);
    assert.equal(tiles.length, count, `expected ${count} tiles`);
    const totalArea = tiles.reduce((sum, t) => sum + t.width * t.height, 0);
    if (count < 4 || count % 2 === 0) {
      assert.ok(
        Math.abs(totalArea - area.width * area.height) < 1,
        `tiles for count=${count} should exactly cover the work area, got total ${totalArea}`
      );
    }
    for (const t of tiles) {
      assert.ok(t.x >= area.x && t.y >= area.y, `tile out of bounds for count=${count}`);
      assert.ok(t.x + t.width <= area.x + area.width + 0.01, `tile overflows width for count=${count}`);
      assert.ok(t.y + t.height <= area.y + area.height + 0.01, `tile overflows height for count=${count}`);
    }
  }
});

// ── reopen (`las widget`) forgets saved position, keeps color/prefs ────────
// The saved-bounds restore is meant for a plain relaunch (`las start`); the
// explicit reopen command exists to grab a widget that is stuck or hard to
// find, so reappearing at the exact same spot would defeat the point.

test('reopenWidget passes forgetPosition so createWidgetWindow skips the saved bounds', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function reopenWidget(name)');
  assert.match(body, /createWidgetWindow\(name,\s*\{\s*forgetPosition:\s*true\s*\}\)/);
});

test('createWidgetWindow only consults getSavedBounds when forgetPosition is false', () => {
  const src = readSrc('main.js');
  assert.match(src, /const saved = !forgetPosition && getSavedBounds\(name\);/);
});

test('openWidget (plain relaunch path) does not pass forgetPosition, so it keeps restoring the last position', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function openWidget(name)');
  assert.match(body, /createWidgetWindow\(name\)\s*;/, 'openWidget should call createWidgetWindow(name) with no options, preserving saved-bounds restore');
});

// ── door button / `las agent deactivate` (close widget, mark inactive) ─────

test('handleProtocolUrl routes action=close to closeWidget, distinct from reopen/open', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function handleProtocolUrl(rawUrl) {');
  assert.match(body, /action === 'close'/);
  assert.match(body, /closeWidget\(name\)/);
});

test('closeWidget destroys the existing window and does NOT recreate one', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function closeWidget(name) {');
  assert.match(body, /\.destroy\(\)/);
  assert.doesNotMatch(body, /createWidgetWindow/, 'closeWidget must not reopen the widget — that would defeat "put it away"');
});

// ── `las agent rename` (an open widget window must follow the rename) ──────

test('handleProtocolUrl routes action=rename with a `to` param to renameWidget, distinct from close/reopen/open', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function handleProtocolUrl(rawUrl) {');
  assert.match(body, /action === 'rename'/);
  assert.match(body, /renameWidget\(name,\s*to\)/);
});

test('renameWidget destroys the old-name window and creates one under the new name', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function renameWidget(oldName, newName) {');
  assert.match(body, /windows\.get\(oldName\)/, 'must look up the window under the OLD name');
  assert.match(body, /\.destroy\(\)/);
  assert.match(body, /windows\.delete\(oldName\)/, 'must not leave a stale map entry under the old name');
  assert.match(body, /createWidgetWindow\(newName/, 'must open the replacement window under the NEW name');
});

test('renameWidget is a no-op when no window is open under the old name', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'function renameWidget(oldName, newName) {');
  assert.match(body, /if \(!existing \|\| existing\.isDestroyed\(\)\) return;/, 'a rename with nothing open for oldName must not create a window either — that\'s openWidget\'s job, not rename\'s');
});

test('agent:deactivate calls the backend inactive endpoint and destroys the calling window', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, "ipcMain.handle('agent:deactivate', async (event, name) => {");
  assert.match(body, /\/agents\/\$\{encodeURIComponent\(name\)\}\/inactive/, 'must POST to the inactive endpoint');
  assert.match(body, /method:\s*'POST'/);
  assert.match(body, /win\.destroy\(\)/, 'must destroy the window the request came from');
});

test('preload.js exposes deactivateAgent and the wake-enabled getter/setter', () => {
  const src = readSrc('preload.js');
  assert.match(src, /deactivateAgent\s*:/);
  assert.match(src, /setWakeEnabled\s*:/);
  assert.match(src, /getWakeEnabled\s*:/);
});

test('index.html has a door button and a wake-enabled settings checkbox', () => {
  const src = readSrc('renderer', 'index.html');
  assert.match(src, /id="door"/);
  assert.match(src, /id="wakeEnabled"/);
});

test('widget.js wires the door button to deactivateAgent and the wake checkbox to setWakeEnabled', () => {
  const src = readSrc('renderer', 'widget.js');
  assert.match(src, /doorEl\.addEventListener\('click'/);
  assert.match(src, /window\.las\.deactivateAgent\(agentName\)/);
  assert.match(src, /wakeEnabledEl\.addEventListener\('change'/);
  assert.match(src, /window\.las\.setWakeEnabled\(agentName,\s*wakeEnabledEl\.checked\)/);
});

// ── wake-enabled IPC handlers ────────────────────────────────────────────────

test('agent:set-wake-enabled toggles POST/DELETE on the wake-enabled endpoint based on the enabled flag', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, "ipcMain.handle('agent:set-wake-enabled', async (_event, name, enabled) => {");
  assert.match(body, /\/wake-enabled/);
  assert.match(body, /method:\s*enabled \? 'POST' : 'DELETE'/);
});

// ── name sizing/line-breaking (ported smartSplit/fitFontSizeAndSplit) ──────

test('smartSplit breaks at the space/hyphen closest to the middle, else the camelCase boundary closest to the middle, else leaves text alone', () => {
  const src = readSrc('renderer', 'widget.js');
  const body = extractFunctionBody(src, 'function smartSplit(text) {');
  const smartSplit = new Function(`function smartSplit(text) ${body} return smartSplit;`)();
  assert.equal(smartSplit('Minis App Acces'), 'Minis App\nAcces');
  assert.equal(smartSplit('LocalAgentSociety'), 'LocalAgent\nSociety');
  assert.equal(smartSplit('agentname'), 'agentname');
});

test('fitNameToBox shrinks the compact font from COMPACT_START_SIZE down to fit, and applies pre-line white-space only when split', () => {
  const src = readSrc('renderer', 'widget.js');
  assert.match(src, /const COMPACT_START_SIZE = 32;/);
  assert.match(src, /const COMPACT_MIN_SIZE = 13;/);
  const body = extractFunctionBody(src, 'function fitNameToBox() {');
  assert.match(body, /nameEl\.style\.whiteSpace = isSplit \? 'pre-line' : 'nowrap';/);
});

test('occlusion-expanded name fill is solid black with no text-stroke, per explicit request', () => {
  const src = readSrc('renderer', 'widget.css');
  const idx = src.indexOf('.widget.occlusion-expanded .name {');
  assert.notEqual(idx, -1);
  const block = src.slice(idx, src.indexOf('}', idx));
  assert.match(block, /color:\s*#000/);
  assert.match(block, /-webkit-text-stroke:\s*0/);
});

test('the door button always stays visible (both compact and settings-open) while every other face button hides in settings-open', () => {
  const css = readSrc('renderer', 'widget.css');
  assert.match(css, /\.widget\.settings-open \.buttonbar \.facebtn:not\(#gear\)\s*\{\s*display:\s*none;/);
  assert.doesNotMatch(css, /\.widget\.settings-open[^{]*door[^{]*\{\s*display:\s*none/);
});

test('restore-after-visible delay is a single named constant, easy to retune to whatever value is currently set', () => {
  const src = readSrc('renderer', 'widget.js');
  assert.match(src, /const RESTORE_DELAY_MS = \d+;/, 'RESTORE_DELAY_MS must stay a bare numeric literal, not an expression, so it stays a one-line, easy-to-retune knob');
  const body = extractFunctionBody(src, "document.addEventListener('visibilitychange', () => {");
  assert.match(body, /hidden \? 400 : RESTORE_DELAY_MS/, 'hide path keeps its short flicker-guard debounce; the show path uses the configurable restore delay');
});

// ── inactive agents must NOT come back on a bulk/auto open ──────────────────
// `las start`'s plain launch (no args) hits the "open everything" branch;
// only a deliberate single-agent open (explicit --agent=/cwd .las-agent.json, or
// `las widget NAME`/wake-via-vortexia — neither goes through this branch)
// should ever open an inactive widget.

test('the bulk "open everything" startup branch skips agents marked inactive', () => {
  const src = readSrc('main.js');
  const body = extractFunctionBody(src, 'app.whenReady().then(async () => {');
  const bulkBranch = body.slice(body.indexOf('} else {'));
  assert.match(bulkBranch, /if \(!agents\[name\]\.inactive\) openWidget\(name\);/);
});

test('visible and active are correlated: openWidget/reopenWidget both clear the inactive flag remotely on every deliberate single-agent open', () => {
  const src = readSrc('main.js');
  assert.match(
    readSrc('main.js'),
    /function clearInactiveRemote\(name\) \{[\s\S]*?method: 'DELETE'/,
    'clearInactiveRemote must DELETE the inactive flag'
  );
  const openBody = extractFunctionBody(src, 'function openWidget(name) {');
  const reopenBody = extractFunctionBody(src, 'function reopenWidget(name) {');
  assert.match(openBody, /clearInactiveRemote\(name\)/);
  assert.match(reopenBody, /clearInactiveRemote\(name\)/);
});
