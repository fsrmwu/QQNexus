// QQNexus preload - expose a safe ipcRenderer bridge to the renderer
const { contextBridge, ipcRenderer } = require('electron');

const api = {
  invoke: (channel, ...args) => ipcRenderer.invoke(channel, ...args),
  on: (channel, cb) => {
    const wrapped = (_e, ...args) => cb(...args);
    ipcRenderer.on(channel, wrapped);
    return () => ipcRenderer.removeListener(channel, wrapped);
  },
  send: (channel, ...args) => ipcRenderer.send(channel, ...args),
};

if (process.contextIsolated) {
  contextBridge.exposeInMainWorld('ipcRenderer', api);
} else {
  window.ipcRenderer = api;
}
