import { contextBridge, ipcRenderer } from 'electron'
import { CHANNELS, type CoreStatus, type DesktopApi } from '../shared/contracts'

const api: DesktopApi = {
  getStatus: () => ipcRenderer.invoke(CHANNELS.status),
  retryCore: () => ipcRenderer.invoke(CHANNELS.retry),
  listMeetings: () => ipcRenderer.invoke(CHANNELS.meetings),
  onStatusChanged: (listener) => {
    const handler = (_event: Electron.IpcRendererEvent, status: CoreStatus): void =>
      listener(status)
    ipcRenderer.on(CHANNELS.statusChanged, handler)
    return () => ipcRenderer.removeListener(CHANNELS.statusChanged, handler)
  },
}

contextBridge.exposeInMainWorld('paa', api)
