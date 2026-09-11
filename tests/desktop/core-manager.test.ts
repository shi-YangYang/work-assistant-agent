import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
import { CoreManager } from '../../src/desktop/core-manager'
import { coreLaunch, pythonCommand } from '../../src/desktop/python-command'

const managers: CoreManager[] = []
const createManager = (): CoreManager => {
  const manager = new CoreManager(process.cwd(), mkdtempSync(join(tmpdir(), 'paa-manager-')))
  managers.push(manager)
  return manager
}

afterEach(async () => {
  await Promise.all(managers.splice(0).map((manager) => manager.stop()))
  vi.unstubAllEnvs()
})

it('selects a single executable and platform-specific fallback', () => {
  expect(pythonCommand('/nonexistent', { PAA_PYTHON: '/a path/python' }, 'darwin')).toEqual({
    command: '/a path/python',
    args: [],
  })
  expect(pythonCommand('/nonexistent', {}, 'win32')).toEqual({ command: 'py', args: ['-3.12'] })
  expect(pythonCommand('/nonexistent', {}, 'darwin')).toEqual({ command: 'python3', args: [] })
})

it('connects to actual Python, returns an empty list, and retries with one new process', async () => {
  const manager = createManager()
  const [first, duplicate] = await Promise.all([manager.start(), manager.start()])
  expect(first.connection).toBe('ready')
  expect(first.processId).toBe(duplicate.processId)
  expect(await manager.listMeetings()).toEqual({ ok: true, meetings: [], hasMore: false })
  const second = await manager.start()
  expect(second.connection).toBe('ready')
  expect(second.processId).not.toBe(first.processId)
  expect(() => process.kill(first.processId!, 0)).toThrow()
  await manager.stop()
  expect(() => process.kill(second.processId!, 0)).toThrow()
})

it('publishes an unexpected exit and can reconnect', async () => {
  const manager = createManager()
  const status = await manager.start()
  expect(status.connection).toBe('ready')
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
})

it('returns a recoverable status when Python is missing', async () => {
  vi.stubEnv('PAA_PYTHON', '/nonexistent/paa-python')
  const manager = createManager()
  const status = await manager.start()
  expect(status.connection).toBe('error')
  expect(status.message).toContain('Python 3.12')
  expect(await manager.listMeetings()).toMatchObject({ ok: false })
  vi.unstubAllEnvs()
  expect((await manager.start()).connection).toBe('ready')
})

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
