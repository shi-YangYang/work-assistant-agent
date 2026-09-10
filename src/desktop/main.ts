import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  powerMonitor,
  protocol,
  session,
  systemPreferences,
  type IpcMainInvokeEvent,
} from 'electron'
import { isAbsolute, join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { CoreManager } from './core-manager'
import { serveMedia } from './media'
import {
  ACTIVE_STATES,
  CHANNELS,
  ID_PATTERN,
  type CoreStatus,
  type RecordingStatus,
  type Result,
} from '../shared/contracts'

app.setName('个人工作助手')
// Tests opt into a separate userData directory before acquiring the single-instance lock.
if (process.env.PAA_TEST_DATA_DIR) {
  if (!isAbsolute(process.env.PAA_TEST_DATA_DIR))
    throw new Error('Test data directory must be absolute')
  app.setPath('userData', process.env.PAA_TEST_DATA_DIR)
}
const hasLock = app.requestSingleInstanceLock()
if (!hasLock) app.quit()
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'paa-audio',
    privileges: { standard: true, secure: true, stream: true, supportFetchAPI: true },
  },
])
const core = new CoreManager(app.getAppPath(), app.getPath('userData'))
let window: BrowserWindow | undefined
let quitting = false
let lifecycle: Promise<boolean> | undefined
let startingRecording: Promise<Result<RecordingStatus>> | undefined
const rendererFile = join(__dirname, '../renderer/index.html')
const devUrl = process.env.ELECTRON_RENDERER_URL
const rendererUrl = new URL(devUrl ?? pathToFileURL(rendererFile).href).href

function trustedCaller(event: IpcMainInvokeEvent): void {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame ||
    event.senderFrame.url !== rendererUrl
  )
    throw new Error('Request is not allowed')
}
function parameters(args: unknown[], kind: 'none' | 'id' | 'offset' | 'transcript'): void {
  if (kind === 'transcript') {
    if (
      args.length !== 2 ||
      typeof args[0] !== 'string' ||
      !ID_PATTERN.test(args[0]) ||
      !Number.isSafeInteger(args[1]) ||
      Number(args[1]) < -1 ||
      Number(args[1]) > 1_000_000_000
    )
      throw new Error('Invalid parameters')
    return
  }
  const valid =
    kind === 'none'
      ? args.length === 0
      : kind === 'id'
        ? args.length === 1 && typeof args[0] === 'string' && ID_PATTERN.test(args[0])
        : args.length === 1 &&
          typeof args[0] === 'number' &&
          Number.isSafeInteger(args[0]) &&
          args[0] >= 0 &&
          args[0] <= 1_000_000
  if (!valid) throw new Error('Invalid parameters')
}
function notifyError(message: string): void {
  window?.show()
  window?.focus()
  window?.webContents.send(CHANNELS.lifecycleError, message)
}
async function protectSession(action: 'exit' | 'retry' | 'suspend'): Promise<boolean> {
  if (core.getStatus().connection !== 'ready') return true
  if (startingRecording) await startingRecording
  const status = await core.recordingStatus()
  if (!status.ok) {
    notifyError(status.message)
    return false
  }
  if (!ACTIVE_STATES.includes(status.value.state)) {
    if (action !== 'suspend' && (await core.transcriptionActive())) {
      if (!window) return false
      const answer = await dialog.showMessageBox(window, {
        type: 'question',
        title: '文字仍在转写',
        message: '保留当前转写进度？',
        detail: '已保存文字会保留，下次打开会议可继续处理剩余音频。',
        buttons: ['继续处理', action === 'exit' ? '保留进度并退出' : '保留进度并重连'],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      })
      if (answer.response === 0) return false
    }
    await core.pauseTranscription()
    return true
  }
  if (action !== 'suspend') {
    if (!window) return false
    window.show()
    const answer = await dialog.showMessageBox(window, {
      type: 'question',
      title: '会议仍在录音',
      message: '先保存这场会议？',
      detail:
        action === 'exit'
          ? '停止采集并保存完成后，应用才会退出。'
          : '停止采集并保存完成后，应用才会重新连接。',
      buttons: ['继续录音', action === 'exit' ? '停止并保存后退出' : '停止并保存后重连'],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    })
    if (answer.response === 0) return false
  }
  try {
    await core.finishRecording(action === 'suspend')
    await core.pauseTranscription()
    return true
  } catch (error) {
    notifyError(error instanceof Error ? error.message : '保存未完成，请检查会议记录。')
    return false
  }
}
function runLifecycle(action: 'exit' | 'retry' | 'suspend'): Promise<boolean> {
  if (lifecycle) return lifecycle
  lifecycle = (async () => {
    if (!(await protectSession(action))) return false
    if (action === 'exit') {
      await core.stop()
      quitting = true
      app.quit()
    } else if (action === 'retry') await core.start()
    return true
  })()
    .catch((error: unknown) => {
      notifyError(error instanceof Error ? error.message : '操作未完成。')
      return false
    })
    .finally(() => {
      lifecycle = undefined
    })
  return lifecycle
}
async function startRecording(operationId: string): Promise<Result<RecordingStatus>> {
  if (lifecycle) return { ok: false, message: '正在处理会议保存，请稍后再开始。' }
  if (!startingRecording)
    startingRecording = (async () => {
      if (process.platform === 'darwin') {
        let access = systemPreferences.getMediaAccessStatus('microphone')
        if (access === 'not-determined')
          access = (await systemPreferences.askForMediaAccess('microphone')) ? 'granted' : 'denied'
        if (access !== 'granted')
          return {
            ok: false as const,
            code: 'microphone_denied',
            message:
              '麦克风权限未开启。请在系统设置 → 隐私与安全性 → 麦克风中允许此应用，再重新启动。',
          }
      }
      return core.startRecording(operationId)
    })().finally(() => {
      startingRecording = undefined
    })
  return startingRecording
}
function createWindow(): void {
  if (devUrl) {
    const url = new URL(devUrl)
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.port !== '5173')
      throw new Error('Development renderer must use the configured loopback address')
  }
  window = new BrowserWindow({
    width: 1240,
    height: 820,
    minWidth: 900,
    minHeight: 640,
    show: false,
    title: '个人工作助手',
    backgroundColor: '#f8f9f6',
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  })
  window.removeMenu()
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-navigate', (event) => event.preventDefault())
  window.webContents.on('will-redirect', (event) => event.preventDefault())
  window.webContents.on('will-attach-webview', (event) => event.preventDefault())
  window.once('ready-to-show', () => window?.show())
  window.on('close', (event) => {
    if (!quitting) {
      event.preventDefault()
      void runLifecycle('exit')
    }
  })
  window.on('closed', () => {
    window = undefined
  })
  const loading = devUrl ? window.loadURL(rendererUrl) : window.loadFile(rendererFile)
  void loading.catch(() => console.error('[desktop] Unable to load the local interface.'))
}
if (hasLock)
  void app.whenReady().then(() => {
    // Native Python capture has its own permission check; no Chromium device access is needed.
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) =>
      callback(false),
    )
    session.defaultSession.setPermissionCheckHandler(() => false)
    session.defaultSession.setDevicePermissionHandler(() => false)
    protocol.handle('paa-audio', (request) => serveMedia(request, app.getPath('userData'), core))
    const register = (
      channel: string,
      kind: 'none' | 'id' | 'offset' | 'transcript',
      handler: (...args: unknown[]) => unknown,
    ): void => {
      ipcMain.handle(channel, (event, ...args: unknown[]) => {
        trustedCaller(event)
        parameters(args, kind)
        return handler(...args)
      })
    }
    register(CHANNELS.modelStatus, 'none', () => core.modelState())
    register(CHANNELS.modelDownload, 'none', () => core.modelState('download'))
    register(CHANNELS.modelCancel, 'none', () => core.modelState('cancel'))
    register(CHANNELS.transcriptionStart, 'id', (id) =>
      core.transcriptionStatus(id as string, true),
    )
    register(CHANNELS.transcriptionStatus, 'id', (id) => core.transcriptionStatus(id as string))
    register(CHANNELS.transcript, 'transcript', (id, cursor) =>
      core.transcript(id as string, cursor as number),
    )
    register(CHANNELS.status, 'none', () => core.getStatus())
    register(CHANNELS.retry, 'none', async () => {
      await runLifecycle('retry')
      return core.getStatus()
    })
    register(CHANNELS.meetings, 'offset', (offset) => core.listMeetings(offset as number))
    register(CHANNELS.meeting, 'id', (id) => core.getMeeting(id as string))
    register(CHANNELS.recordingStatus, 'none', () => core.recordingStatus())
    register(CHANNELS.recordingStart, 'id', (id) => startRecording(id as string))
    register(CHANNELS.recordingStop, 'id', (id) => core.stopRecording(id as string))
    core.on('status', (status: CoreStatus) => {
      if (window && !window.isDestroyed()) window.webContents.send(CHANNELS.statusChanged, status)
    })
    powerMonitor.on('suspend', () => {
      void core.pauseTranscription().catch(() => undefined)
      // Interrupt immediately even while an exit/retry confirmation is pending.
      void core
        .recordingStatus()
        .then((result) => {
          if (result.ok && result.value.meetingId && ACTIVE_STATES.includes(result.value.state)) {
            return core.stopRecording(result.value.meetingId, true)
          }
          return undefined
        })
        .catch(() => notifyError('系统休眠中断了核心连接，请重新连接以恢复录音。'))
    })
    createWindow()
    void core.start()
  })
app.on('second-instance', () => {
  window?.restore()
  window?.show()
  window?.focus()
})
app.on('window-all-closed', () => app.quit())
app.on('before-quit', (event) => {
  if (quitting || !hasLock) return
  event.preventDefault()
  void runLifecycle('exit')
})
for (const signal of ['SIGINT', 'SIGTERM'] as const) process.on(signal, () => app.quit())
