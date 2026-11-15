'use strict';
/**
 * contextBridge surface for the Phones window (renderer/pairing.html):
 * vortexia's pairing and friends control (lib/pairing.js, ADR 0001 §10),
 * driven by main.js over the local broker.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pairing', {
  state: () => ipcRenderer.invoke('pairing:state'),
  start: (label) => ipcRenderer.invoke('pairing:start', label),
  cancel: () => ipcRenderer.invoke('pairing:cancel'),
  copy: () => ipcRenderer.invoke('pairing:copy'),
  decide: (sessionId, accept) => ipcRenderer.invoke('pairing:decide', sessionId, accept),
  revoke: (envName) => ipcRenderer.invoke('pairing:revoke', envName),
  onState: (cb) => ipcRenderer.on('pairing:state', (_e, state) => cb(state)),
  onEvent: (cb) => ipcRenderer.on('pairing:event', (_e, event) => cb(event)),
});
