import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CHANNELS } from '../../src/shared/contracts'

const state = vi.hoisted(() => ({
  windows: true,
  packaged: true,
  file: String.raw`C:\Users\RUNNER~1\AppData\Local\Temp\paa-install\installed\resources\app.asar\out\renderer\index.html`,
  contents: { mainFrame: { url: '' } },
  handlers: new Map<string, (...args: unknown[]) => unknown>(),
  getStatus: vi.fn(() => ({ connection: 'ready' })),
}))

vi.mock('node:path', async (importOriginal) => {
  const original = await importOriginal<typeof import('node:path')>()
  return {
    ...original,
    join: (...parts: string[]) =>
      parts[1] === '../renderer/index.html' ? state.file : original.join(...parts),
  }
})
vi.mock('node:url', async (importOriginal) => {
  const original = await importOriginal<typeof import('node:url')>()
  return {
    ...original,
    pathToFileURL: (file: string) => original.pathToFileURL(file, { windows: state.windows }),
  }
})
vi.mock('electron', async () => {
  const { format } = await vi.importActual<typeof import('node:url')>('node:url')
  return {
    app: {
      setName: vi.fn(),
      setPath: vi.fn(),
      requestSingleInstanceLock: () => true,
      getAppPath: () => '/app',
      getPath: () => '/user-data',
      get isPackaged() {
        return state.packaged
      },
      whenReady: () => Promise.resolve(),
      on: vi.fn(),
    },
    BrowserWindow: class {
      webContents = Object.assign(state.contents, {
        setWindowOpenHandler: vi.fn(),
        on: vi.fn(),
      })
      removeMenu = vi.fn()
      once = vi.fn()
      on = vi.fn()
      async loadURL(url: string) {
        this.webContents.mainFrame.url = new URL(url).href
      }
      async loadFile(file: string) {
        // Electron 44.3.0 uses legacy url.format in loadFile, not pathToFileURL.
        await this.loadURL(format({ protocol: 'file', slashes: true, pathname: file }))
      }
    },
    ipcMain: {
      handle: (channel: string, handler: (...args: unknown[]) => unknown) =>
        state.handlers.set(channel, handler),
    },
    protocol: { registerSchemesAsPrivileged: vi.fn(), handle: vi.fn() },
    powerMonitor: { on: vi.fn() },
    session: {
      defaultSession: {
        setPermissionRequestHandler: vi.fn(),
        setPermissionCheckHandler: vi.fn(),
        setDevicePermissionHandler: vi.fn(),
      },
    },
    safeStorage: {},
    systemPreferences: {},
    dialog: {},
  }
})
vi.mock('../../src/desktop/core-manager', () => ({
  CoreManager: class {
    getStatus = state.getStatus
    on = vi.fn()
    start = async () => ({ connection: 'ready' })
  },
}))
vi.mock('../../src/desktop/summary-settings', () => ({
  SummarySettings: class {
    load = async () => {}
    sync = async () => {}
  },
}))

let signalListeners: Map<NodeJS.Signals, Set<(signal: NodeJS.Signals) => void>>
beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  vi.stubEnv('PAA_TEST_DATA_DIR', '')
  vi.stubEnv('ELECTRON_RENDERER_URL', 'https://must-not-load.invalid')
  state.windows = true
  state.packaged = true
  state.file = String.raw`C:\Users\RUNNER~1\AppData\Local\Temp\paa-install\installed\resources\app.asar\out\renderer\index.html`
  state.contents = { mainFrame: { url: '' } }
  state.handlers.clear()
  signalListeners = new Map(
    (['SIGINT', 'SIGTERM'] as const).map((signal) => [signal, new Set(process.listeners(signal))]),
  )
})
afterEach(() => {
  for (const [signal, existing] of signalListeners)
    for (const listener of process.listeners(signal))
      if (!existing.has(listener)) process.removeListener(signal, listener)
  vi.unstubAllEnvs()
})

async function start() {
  await import('../../src/desktop/main')
  await vi.waitFor(() => expect(state.contents.mainFrame.url).not.toBe(''))
  const invoke = state.handlers.get(CHANNELS.status)!
  return () => invoke({ sender: state.contents, senderFrame: state.contents.mainFrame })
}

it('allows installed Windows IPC from a short path containing a tilde', async () => {
  const status = await start()
  expect(state.contents.mainFrame.url).toContain('/RUNNER%7E1/')
  expect(status()).toEqual({ connection: 'ready' })
})

it.each([
  [true, String.raw`C:\用户\会议 #100%\resources\app.asar\out\renderer\index.html`],
  [false, '/Applications/个人工作助手.app/Contents/Resources/app.asar/out/renderer/index.html'],
])('allows the encoded packaged renderer (Windows=%s)', async (windows, file) => {
  state.windows = windows
  state.file = file
  expect((await start())()).toEqual({ connection: 'ready' })
})

it('retains the exact configured development URL', async () => {
  state.packaged = false
  vi.stubEnv('ELECTRON_RENDERER_URL', 'http://127.0.0.1:5173/')
  const status = await start()
  expect(state.contents.mainFrame.url).toBe('http://127.0.0.1:5173/')
  expect(status()).toEqual({ connection: 'ready' })
})

it('rejects other pages, query/fragment changes, other windows and subframes', async () => {
  const status = await start()
  const url = state.contents.mainFrame.url
  for (const untrusted of [
    'https://example.com/',
    'about:blank',
    url.replace('index.html', 'other.html'),
    `${url}?source=other`,
    `${url}#other`,
    `${url}/other`,
    url.replace('%7E', '~'),
  ]) {
    state.contents.mainFrame.url = untrusted
    expect(status).toThrow('Request is not allowed')
  }
  state.contents.mainFrame.url = url
  const invoke = state.handlers.get(CHANNELS.status)!
  for (const event of [
    { sender: {}, senderFrame: state.contents.mainFrame },
    { sender: state.contents, senderFrame: { url } },
    { sender: state.contents, senderFrame: null },
  ])
    expect(() => invoke(event)).toThrow('Request is not allowed')
  expect(state.getStatus).not.toHaveBeenCalled()
})
