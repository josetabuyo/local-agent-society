'use strict';
/**
 * contextBridge surface for the hidden audio decoder window
 * (renderer/decoder.html): main hands it compressed audio (a phone's m4a,
 * lib/deviceAudio.js), it answers with mono 16 kHz Float32 PCM — Chromium's
 * decodeAudioData does AAC/Opus/MP3 on every platform, which the main
 * process (no WebAudio) can't.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('decoder', {
  /** @param {(id: number, bytes: ArrayBuffer) => void} cb */
  onRequest: (cb) => ipcRenderer.on('decoder:request', (_e, id, bytes) => cb(id, bytes)),
  reply: (id, pcm, error) => ipcRenderer.send('decoder:reply', id, pcm || null, error || null),
});
