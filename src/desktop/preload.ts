import { contextBridge, ipcRenderer } from 'electron'
import { CHANNELS, type CoreStatus, type DesktopApi } from '../shared/contracts'
const api: DesktopApi = {
  getTranscriptionModel: () => ipcRenderer.invoke(CHANNELS.modelStatus),
  downloadTranscriptionModel: () => ipcRenderer.invoke(CHANNELS.modelDownload),
  cancelModelDownload: () => ipcRenderer.invoke(CHANNELS.modelCancel),
  startTranscription: (id) => ipcRenderer.invoke(CHANNELS.transcriptionStart, id),
  getTranscriptionStatus: (id) => ipcRenderer.invoke(CHANNELS.transcriptionStatus, id),
  listTranscript: (id, cursor = -1) => ipcRenderer.invoke(CHANNELS.transcript, id, cursor),
  getStatus: () => ipcRenderer.invoke(CHANNELS.status),
  retryCore: () => ipcRenderer.invoke(CHANNELS.retry),
  listMeetings: (offset = 0) => ipcRenderer.invoke(CHANNELS.meetings, offset),
  getMeeting: (id) => ipcRenderer.invoke(CHANNELS.meeting, id),
  getRecordingStatus: () => ipcRenderer.invoke(CHANNELS.recordingStatus),
  startRecording: (id) => ipcRenderer.invoke(CHANNELS.recordingStart, id),
  stopRecording: (id) => ipcRenderer.invoke(CHANNELS.recordingStop, id),
  onStatusChanged: (listener) => {
    const handler = (_event: Electron.IpcRendererEvent, status: CoreStatus): void =>
      listener(status)
    ipcRenderer.on(CHANNELS.statusChanged, handler)
    return () => ipcRenderer.removeListener(CHANNELS.statusChanged, handler)
  },
  onLifecycleError: (listener) => {
    const handler = (_event: Electron.IpcRendererEvent, message: string): void => listener(message)
    ipcRenderer.on(CHANNELS.lifecycleError, handler)
    return () => ipcRenderer.removeListener(CHANNELS.lifecycleError, handler)
  },
}
contextBridge.exposeInMainWorld('paa', api)
