const { contextBridge, ipcRenderer } = require('electron');

// Expose API to renderer process
contextBridge.exposeInMainWorld('electronAPI', {
  // API methods will be added here as needed
  platform: process.platform,
  openExternal: (url) => ipcRenderer.invoke('open-external', url)
});