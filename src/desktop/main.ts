import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent, session } from 'electron'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { CoreManager } from './core-manager'
import { CHANNELS, type CoreStatus } from '../shared/contracts'

app.setName('个人工作助手')

const core = new CoreManager(app.getAppPath())
let window: BrowserWindow | undefined
let quitting = false
const rendererFile = join(__dirname, '../renderer/index.html')
const devUrl = process.env.ELECTRON_RENDERER_URL
const rendererUrl = new URL(devUrl ?? pathToFileURL(rendererFile).href).href

function trustedCaller(event: IpcMainInvokeEvent, args: unknown[]): void {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame ||
    event.senderFrame.url !== rendererUrl ||
    args.length !== 0
  ) {
    throw new Error('Request is not allowed')
  }
}

function createWindow(): void {
  if (devUrl) {
    const url = new URL(devUrl)
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.port !== '5173') {
      throw new Error('Development renderer must use the configured loopback address')
    }
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
  window.on('closed', () => {
    window = undefined
  })
  const loading = devUrl ? window.loadURL(rendererUrl) : window.loadFile(rendererFile)
  void loading.catch(() => console.error('[desktop] Unable to load the local interface.'))
}

void app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => {
    callback(false)
  })
  session.defaultSession.setPermissionCheckHandler(() => false)
  session.defaultSession.setDevicePermissionHandler(() => false)
  ipcMain.handle(CHANNELS.status, (event, ...args: unknown[]) => {
    trustedCaller(event, args)
    return core.getStatus()
  })
  ipcMain.handle(CHANNELS.retry, (event, ...args: unknown[]) => {
    trustedCaller(event, args)
    return core.start()
  })
  ipcMain.handle(CHANNELS.meetings, (event, ...args: unknown[]) => {
    trustedCaller(event, args)
    return core.listMeetings()
  })
  core.on('status', (status: CoreStatus) => {
    if (window && !window.isDestroyed()) window.webContents.send(CHANNELS.statusChanged, status)
  })
  createWindow()
  void core.start()
})

app.on('window-all-closed', () => app.quit())
app.on('before-quit', (event) => {
  if (quitting) return
  event.preventDefault()
  quitting = true
  void core.stop().finally(() => app.quit())
})

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => app.quit())
}
