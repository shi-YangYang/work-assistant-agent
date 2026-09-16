import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { afterEach, expect, it, vi } from 'vitest'
import { CoreManager } from '../../apps/desktop/src/main/core-manager'
import { coreLaunch, pythonCommand } from '../../apps/desktop/src/main/python-command'
import { UNAVAILABLE_CAPABILITIES } from '../../apps/desktop/src/shared/contracts'

vi.mock('node:child_process', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:child_process')>()
  return { ...actual, spawn: vi.fn(actual.spawn) }
})

const managers: CoreManager[] = []
// Reconnection tests initialize the real Python core twice, each with a 15s deadline.
const coreLifecycleTimeout = 40_000
const createManager = (): CoreManager => {
  const manager = new CoreManager(process.cwd(), mkdtempSync(join(tmpdir(), 'paa-manager-')))
  managers.push(manager)
  return manager
}

afterEach(async () => {
  await Promise.all(managers.splice(0).map((manager) => manager.stop()))
  vi.restoreAllMocks()
  vi.useRealTimers()
  vi.unstubAllEnvs()
})

function mockCore(startupDelay: number | null): ChildProcessWithoutNullStreams {
  const child = Object.assign(new EventEmitter(), {
    stdin: new PassThrough(),
    stdout: new PassThrough(),
    stderr: new PassThrough(),
    pid: 12345,
    exitCode: null as number | null,
    signalCode: null,
    kill: vi.fn(() => {
      child.exitCode = 0
      child.emit('exit', 0)
      child.emit('close', 0)
      return true
    }),
  })
  child.stdin.on('data', (line: Buffer) => {
    const request = JSON.parse(line.toString())
    const reply = (result: unknown): void => {
      child.stdout.write(JSON.stringify({ id: request.id, result }) + '\n')
    }
    if (request.method === 'health' && startupDelay !== null) {
      setTimeout(
        () =>
          reply({
            pythonVersion: '3.12.0',
            processId: child.pid,
            capabilities: UNAVAILABLE_CAPABILITIES,
          }),
        startupDelay,
      )
    }
    if (request.method === 'recording.status') {
      reply({
        meetingId: null,
        state: 'idle',
        elapsedMs: 0,
        deviceName: null,
        inputLevel: 0,
        error: null,
      })
    }
    if (request.method === 'shutdown') reply({ stopping: true })
  })
  const process = child as unknown as ChildProcessWithoutNullStreams
  vi.mocked(spawn).mockReturnValueOnce(process)
  return process
}

it('allows slow hardware initialization while keeping normal requests bounded', async () => {
  vi.useFakeTimers()
  mockCore(4_000)
  const manager = createManager()
  const startup = manager.start()
  await vi.advanceTimersByTimeAsync(4_000)
  expect((await startup).connection).toBe('ready')
  const request = manager.listMeetings()
  await vi.advanceTimersByTimeAsync(3_000)
  expect(await request).toMatchObject({ ok: false, code: 'timeout' })
})

it('stops a core that never finishes initialization within the startup deadline', async () => {
  vi.useFakeTimers()
  const child = mockCore(null)
  const manager = createManager()
  const startup = manager.start()
  await vi.advanceTimersByTimeAsync(14_999)
  expect(manager.getStatus().connection).toBe('starting')
  await vi.advanceTimersByTimeAsync(1)
  expect((await startup).connection).toBe('error')
  expect(child.kill).toHaveBeenCalledOnce()
})

it('selects a single executable and platform-specific fallback', () => {
  expect(pythonCommand('/nonexistent', { PAA_PYTHON: '/a path/python' }, 'darwin')).toEqual({
    command: '/a path/python',
    args: [],
  })
  expect(pythonCommand('/nonexistent', {}, 'win32')).toEqual({ command: 'py', args: ['-3.12'] })
  expect(pythonCommand('/nonexistent', {}, 'darwin')).toEqual({ command: 'python3', args: [] })
})

it(
  'connects to actual Python, returns an empty list, and retries with one new process',
  async () => {
    const manager = createManager()
    const [first, duplicate] = await Promise.all([manager.start(), manager.start()])
    expect(first.connection, first.message).toBe('ready')
    expect(first.processId).toBe(duplicate.processId)
    expect(await manager.listMeetings()).toEqual({ ok: true, meetings: [], hasMore: false })
    const second = await manager.start()
    expect(second.connection, second.message).toBe('ready')
    expect(second.processId).not.toBe(first.processId)
    expect(() => process.kill(first.processId!, 0)).toThrow()
    await manager.stop()
    expect(() => process.kill(second.processId!, 0)).toThrow()
  },
  coreLifecycleTimeout,
)

it(
  'publishes an unexpected exit and can reconnect',
  async () => {
    const manager = createManager()
    const status = await manager.start()
    expect(status.connection, status.message).toBe('ready')
    const failed = new Promise<void>((resolve) =>
      manager.on('status', (next) => {
        if (next.connection === 'error') resolve()
      }),
    )
    process.kill(status.processId!)
    await failed
    expect(manager.getStatus().connection).toBe('error')
    expect(await manager.listMeetings()).toMatchObject({ ok: false })
    expect((await manager.start()).connection).toBe('ready')
  },
  coreLifecycleTimeout,
)

it(
  'returns a recoverable status when Python is missing',
  async () => {
    vi.stubEnv('PAA_PYTHON', '/nonexistent/paa-python')
    const manager = createManager()
    const status = await manager.start()
    expect(status.connection).toBe('error')
    expect(status.message).toContain('Python 3.12')
    expect(await manager.listMeetings()).toMatchObject({ ok: false })
    vi.unstubAllEnvs()
    expect((await manager.start()).connection).toBe('ready')
  },
  coreLifecycleTimeout,
)

it('stopping during startup cannot leave a process or return ready', async () => {
  const manager = createManager()
  const startup = manager.start()
  await manager.stop()
  await startup
  expect(manager.getStatus().connection).toBe('stopped')
  expect((await manager.start()).connection).toBe('stopped')
})

it('packaged launch is rooted in resources and ignores development Python overrides', () => {
  expect(
    coreLaunch(
      '/missing/source',
      '/user data',
      '/中文 App/resources',
      { PAA_PYTHON: '/wrong/python' },
      'win32',
    ),
  ).toEqual({
    command: join('/中文 App/resources', 'paa-core', 'paa-core.exe'),
    args: ['--data-dir', '/user data'],
    cwd: join('/中文 App/resources', 'paa-core'),
  })
})
it('missing packaged runtime reports an application fault without system fallback', async () => {
  const manager = new CoreManager(
    '/missing/source',
    mkdtempSync(join(tmpdir(), 'paa-package-')),
    '/missing/resources',
  )
  managers.push(manager)
  const status = await manager.start()
  expect(status.connection).toBe('error')
  expect(status.message).toContain('重新安装应用')
  expect(status.message).not.toContain('Python')
})

it(
  'exposes six pinned local models and validates settings before mutating defaults',
  async () => {
    const manager = createManager()
    const status = await manager.start()
    expect(status.connection, status.message).toBe('ready')
    const catalog = await manager.modelState()
    expect(catalog.ok).toBe(true)
    if (!catalog.ok) return
    expect(catalog.value.models.map((model) => model.id)).toEqual([
      'tiny',
      'base',
      'small',
      'medium',
      'large-v3-turbo',
      'large-v3',
    ])
    expect(catalog.value.defaultModel).toBe('small')
    expect(catalog.value.language).toBe('zh')
    expect(catalog.value.hardware.cpuName).not.toBe('')
    expect(catalog.value.device).toBe(catalog.value.hardware.gpuAvailable ? 'gpu' : 'cpu')
    expect(await manager.modelState('device', { device: 'cpu' })).toMatchObject({
      ok: true,
      value: { device: 'cpu', backend: 'ctranslate2' },
    })
    expect(await manager.modelState('device', { device: 'automatic' })).toMatchObject({
      ok: false,
      code: 'invalid_device',
    })
    expect(
      await manager.modelState('manage', { action: 'configure', id: 'small', language: 'en' }),
    ).toMatchObject({ ok: true, value: { language: 'en' } })
    expect(
      await manager.modelState('manage', {
        action: 'configure',
        id: '../model',
        language: 'mixed',
      }),
    ).toMatchObject({ ok: false, code: 'invalid_model' })
    expect(
      await manager.modelState('manage', {
        action: 'configure',
        id: 'large-v3',
        language: 'mixed',
      }),
    ).toMatchObject({ ok: false, code: 'model_not_ready' })
    expect(
      await manager.modelState('manage', { action: 'remove', id: 'small', language: null }),
    ).toMatchObject({ ok: false, code: 'model_in_use' })
    expect(await manager.modelState()).toMatchObject({
      ok: true,
      value: { defaultModel: 'small', language: 'en' },
    })
    await manager.start()
    expect(await manager.modelState()).toMatchObject({
      ok: true,
      value: { defaultModel: 'small', language: 'en', device: 'cpu' },
    })
  },
  coreLifecycleTimeout,
)
