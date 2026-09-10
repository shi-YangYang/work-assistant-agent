import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test'
import { mkdirSync, mkdtempSync, writeFileSync, chmodSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
const roots: string[] = []
mkdirSync('artifacts/spec002', { recursive: true })
function temp(): string {
  const root = mkdtempSync(join(tmpdir(), 'paa-smoke 会议-'))
  roots.push(root)
  return root
}
async function launch(
  dataRoot: string,
  synthetic = false,
  extraEnv: Record<string, string> = {},
): Promise<ElectronApplication> {
  const env = Object.fromEntries(
    Object.entries({ ...process.env, PAA_TEST_DATA_DIR: dataRoot, ...extraEnv }).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string',
    ),
  )
  if (synthetic) {
    const shim = join(dataRoot, 'synthetic-python')
    const quote = (value: string): string => `'${value.replaceAll("'", "'\\''")}'`
    writeFileSync(
      shim,
      `#!/bin/sh\nexec ${quote(resolve('.venv/bin/python'))} ${quote(resolve('tests/python/smoke_core.py'))} "$@"\n`,
    )
    chmodSync(shim, 0o755)
    env.PAA_PYTHON = shim
  }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.ELECTRON_RENDERER_URL
  // Supply capture devices even on CI runners without hardware; keep permission checks enabled.
  return electron.launch({ args: ['--use-fake-device-for-media-stream', resolve('.')], env })
}
async function ready(app: ElectronApplication) {
  const page = await app.firstWindow()
  await expect
    .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
    .toBe('ready')
  return page
}
async function recordingState(app: ElectronApplication): Promise<string> {
  const page = await app.firstWindow()
  const result = await page.evaluate(() => window.paa.getRecordingStatus())
  return result.ok ? result.value.state : result.message
}
test.afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
})

test('real desktop exposes actual capabilities and empty history with strict boundaries', async () => {
  const app = await launch(temp())
  try {
    const page = await ready(app)
    await expect(page.getByRole('button', { name: '开始会议', exact: true })).toBeEnabled()
    await expect(page.getByText('暂无会议记录', { exact: true })).toBeVisible()
    expect((await page.evaluate(() => window.paa.getStatus())).capabilities).toEqual([
      { id: 'recording', available: true },
      { id: 'transcription', available: false },
      { id: 'summary', available: false },
    ])
    expect(
      await page.evaluate(() => ({ node: typeof process, require: typeof window.require })),
    ).toEqual({ node: 'undefined', require: 'undefined' })
    const sandboxed = await app.evaluate(({ app, BrowserWindow }) => {
      const pid = BrowserWindow.getAllWindows()[0].webContents.getOSProcessId()
      return app.getAppMetrics().find((metric) => metric.pid === pid)?.sandboxed
    })
    expect(sandboxed).toBe(true)
    await expect(page.locator('meta[http-equiv="Content-Security-Policy"]')).toHaveAttribute(
      'content',
      /media-src paa-audio:/,
    )
    expect(
      await page.evaluate(async () => {
        try {
          await window.paa.getMeeting('../etc/passwd')
          return false
        } catch {
          return true
        }
      }),
    ).toBe(true)
    const permission = await page.evaluate(async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true })
        stream.getTracks().forEach((track) => track.stop())
        return 'unexpectedly granted'
      } catch (error) {
        return (error as DOMException).name
      }
    })
    expect(permission).toBe('NotAllowedError')
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(900, 640))
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.screenshot({ path: 'artifacts/spec002/empty-minimum.png' })
    const pid = (await page.evaluate(() => window.paa.getStatus())).processId!
    process.kill(pid)
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('error')
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await page.getByRole('button', { name: '重新连接', exact: true }).click()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('ready')
    const newPid = (await page.evaluate(() => window.paa.getStatus())).processId!
    const closed = app.waitForEvent('close')
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    await closed
    expect(() => process.kill(newPid, 0)).toThrow()
  } finally {
    await app.close().catch(() => {})
  }
})

test('microphone denial is actionable and never creates a recording', async () => {
  test.skip(process.platform !== 'darwin', 'Native macOS permission adaptation')
  const app = await launch(temp())
  try {
    const page = await ready(app)
    await app.evaluate(({ systemPreferences }) => {
      systemPreferences.getMediaAccessStatus = () => 'denied'
    })
    await page.getByRole('button', { name: '开始会议', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('麦克风权限未开启')
    expect(await recordingState(app)).toBe('idle')
    expect(await page.evaluate(() => window.paa.listMeetings())).toEqual({
      ok: true,
      meetings: [],
      hasMore: false,
    })
  } finally {
    await app.close()
  }
})

test('synthetic capture survives navigation, guards close/retry, saves, restarts and seeks', async () => {
  test.skip(
    process.platform === 'win32',
    'POSIX synthetic executable shim; Windows native recording remains unverified',
  )
  const root = temp()
  let app = await launch(root, true)
  try {
    let page = await ready(app)
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.getByRole('button', { name: '开始会议', exact: true }).click()
    await expect.poll(() => recordingState(app)).toBe('recording')
    const initial = await page.evaluate(() => window.paa.getRecordingStatus())
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await expect(page.getByLabel('活动录音')).toBeVisible()
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].minimize())
    await page.waitForTimeout(200)
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].restore())
    await app.evaluate(({ dialog }) => {
      dialog.showMessageBox = async () => ({ response: 0, checkboxChecked: false })
    })
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    await expect.poll(() => recordingState(app)).toBe('recording')
    await page.getByRole('button', { name: '重新连接', exact: true }).click()
    expect(await recordingState(app)).toBe('recording')
    const current = await page.evaluate(() => window.paa.getRecordingStatus())
    expect(current.ok && initial.ok && current.value.meetingId === initial.value.meetingId).toBe(
      true,
    )
    await page.screenshot({ path: 'artifacts/spec002/synthetic-settings-recording.png' })
    await app.evaluate(({ dialog }) => {
      dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
    })
    const closed = app.waitForEvent('close')
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    await closed
    app = await launch(root, true)
    page = await ready(app)
    await expect(page.locator('.meeting-row')).toHaveCount(1)
    await page.locator('.meeting-row').click()
    await expect(page.locator('.meeting-detail')).toContainText('已完成')
    await expect
      .poll(() => page.locator('audio').evaluate((audio) => (audio as HTMLAudioElement).readyState))
      .toBeGreaterThanOrEqual(1)
    await page.locator('audio').evaluate((element) => {
      const audio = element as HTMLAudioElement
      audio.currentTime = Math.min(0.3, audio.duration / 2)
    })
    await expect
      .poll(() =>
        page.locator('audio').evaluate((audio) => (audio as HTMLAudioElement).currentTime),
      )
      .toBeGreaterThan(0)
    const rows = await page.evaluate(() => window.paa.listMeetings())
    expect(rows.ok && rows.meetings[0].audioAvailable).toBe(true)
    expect(rows.ok && Object.hasOwn(rows.meetings[0], 'audioPath')).toBe(false)
    expect(errors).toEqual([])
  } finally {
    await app.close().catch(() => {})
  }
})

test('synthetic suspend interrupts even while close confirmation is pending; crash recovers', async () => {
  test.skip(process.platform === 'win32', 'POSIX synthetic executable shim')
  const root = temp()
  let app = await launch(root, true)
  try {
    let page = await ready(app)
    await page.getByRole('button', { name: '开始会议', exact: true }).click()
    await expect.poll(() => recordingState(app)).toBe('recording')
    await page.waitForTimeout(150)
    await app.evaluate(({ dialog }) => {
      dialog.showMessageBox = () =>
        new Promise((resolve) =>
          setTimeout(() => resolve({ response: 0, checkboxChecked: false }), 700),
        )
    })
    await app.evaluate(({ BrowserWindow, powerMonitor }) => {
      BrowserWindow.getAllWindows()[0].close()
      setTimeout(() => powerMonitor.emit('suspend'), 30)
    })
    await expect.poll(() => recordingState(app)).toBe('interrupted')
    await expect(page.getByRole('alert')).toContainText('休眠')
    await page.waitForTimeout(700)
    await page.getByRole('button', { name: '开始会议', exact: true }).click()
    await expect.poll(() => recordingState(app)).toBe('recording')
    await page.waitForTimeout(150)
    const pid = (await page.evaluate(() => window.paa.getStatus())).processId!
    process.kill(pid, 'SIGKILL')
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('error')
    await expect(page.getByRole('alert')).toContainText('录音连接已中断')
    await app.close()
    app = await launch(root, true)
    page = await ready(app)
    await expect(page.locator('.meeting-row')).toHaveCount(2)
    const result = await page.evaluate(() => window.paa.listMeetings())
    expect(
      result.ok &&
        result.meetings.every(
          (meeting) => meeting.status === 'interrupted' && meeting.audioAvailable,
        ),
    ).toBe(true)
  } finally {
    await app.close().catch(() => {})
  }
})

test('synthetic save failure keeps the window visible and partial audio retained', async () => {
  test.skip(process.platform === 'win32', 'POSIX synthetic executable shim')
  const app = await launch(temp(), true, { PAA_FIXTURE_FAIL_CLOSE: '1' })
  try {
    const page = await ready(app)
    await page.getByRole('button', { name: '开始会议', exact: true }).click()
    await expect.poll(() => recordingState(app)).toBe('recording')
    await page.waitForTimeout(150)
    await app.evaluate(({ dialog }) => {
      dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
    })
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    await expect.poll(() => recordingState(app)).toBe('interrupted')
    await expect(page.getByRole('alert')).toContainText('保存失败')
    expect(
      await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()),
    ).toBe(true)
    const result = await page.evaluate(() => window.paa.listMeetings())
    expect(result.ok && result.meetings[0].audioAvailable).toBe(true)
  } finally {
    await app.close().catch(() => {})
  }
})

test('missing Python opens the desktop and supports retry', async () => {
  const app = await launch(temp(), false, { PAA_PYTHON: resolve('artifacts/missing-python') })
  try {
    const page = await app.firstWindow()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('error')
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await expect(page.getByRole('button', { name: '重新连接', exact: true })).toBeEnabled()
  } finally {
    await app.close()
  }
})
