import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test'
import { mkdirSync, mkdtempSync, writeFileSync, chmodSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, resolve, join } from 'node:path'
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
    await page.getByRole('button', { name: '模型服务管理', exact: true }).click()
    await page.getByLabel('服务名称', { exact: true }).fill('未保存的草稿')
    await page
      .getByLabel('服务名称', { exact: true })
      .press(process.platform === 'darwin' ? 'Meta+k' : 'Control+k')
    await expect(page.getByRole('dialog', { name: '命令面板' })).toHaveCount(0)
    await page.getByRole('tab', { name: '模型与推理', exact: true }).click()
    await page.getByLabel('模型 ID', { exact: true }).fill('draft-model')
    await page.getByRole('button', { name: '本地转写模型', exact: true }).click()
    await expect(page.getByLabel('服务名称', { exact: true })).toBeHidden()
    await page.getByRole('button', { name: '会议记录', exact: true }).click()
    await page.getByRole('button', { name: '模型服务管理', exact: true }).click()
    await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('draft-model')
    await page.getByRole('tab', { name: '连接配置', exact: true }).click()
    await expect(page.getByLabel('服务名称', { exact: true })).toHaveValue('未保存的草稿')
    await page.getByRole('button', { name: /查找页面与操作/ }).click()
    const palette = page.getByRole('dialog', { name: '命令面板' })
    await palette.getByLabel('查找页面与操作', { exact: true }).fill('外观')
    await palette.getByLabel('查找页面与操作', { exact: true }).press('Enter')
    await expect(page.getByRole('heading', { name: '外观', exact: true })).toBeFocused()
    await page.getByRole('radio', { name: '深色', exact: true }).check()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.getByRole('button', { name: /查找页面与操作/ }).click()
    await palette.press('Escape')
    await expect(page.getByRole('button', { name: /查找页面与操作/ })).toBeFocused()
    await page.getByRole('radio', { name: '跟随系统', exact: true }).check()
    await expect(page.getByRole('heading', { name: '应用状态', exact: true })).toHaveCount(0)
    const pid = (await page.evaluate(() => window.paa.getStatus())).processId!
    process.kill(pid)
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('error')
    await page.getByRole('button', { name: '模型服务管理', exact: true }).click()
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
    await page.getByRole('button', { name: '暂停录音', exact: true }).click()
    await expect.poll(() => recordingState(app)).toBe('paused')
    const paused = await page.evaluate(() => window.paa.getRecordingStatus())
    await page.waitForTimeout(200)
    const stillPaused = await page.evaluate(() => window.paa.getRecordingStatus())
    expect(
      stillPaused.ok && paused.ok && stillPaused.value.elapsedMs === paused.value.elapsedMs,
    ).toBe(true)
    await expect(page.getByRole('button', { name: '开始会议', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: '继续录音', exact: true }).click()
    await expect.poll(() => recordingState(app)).toBe('recording')
    await page.getByRole('button', { name: '模型服务管理', exact: true }).click()
    await expect(page.getByLabel('活动录音')).toBeVisible()
    await expect(page.getByRole('region', { name: '会议文字', exact: true })).toBeHidden()
    await page.getByRole('button', { name: /查找页面与操作/ }).click()
    await expect(page.getByRole('dialog').getByRole('button', { name: /开始会议/ })).toBeDisabled()
    await page.getByRole('dialog').press('Escape')
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
    const player = page.getByRole('region', { name: '会议录音播放器', exact: true })
    // Let periodic status updates reconcile the detail more than once.
    await page.waitForTimeout(1200)
    await expect(player).toHaveCount(1)
    await page.locator('audio').evaluate((element) => {
      element.setAttribute('data-instance', 'original')
    })
    await page.getByRole('tab', { name: '文字记录', exact: true }).click()
    await page.getByRole('tab', { name: '纪要', exact: true }).click()
    await expect(page.locator('audio')).toHaveAttribute('data-instance', 'original')
    await player.getByRole('button', { name: '前进 10 秒', exact: true }).click()
    await expect
      .poll(() =>
        page
          .locator('audio')
          .evaluate((element) =>
            Math.abs(
              (element as HTMLAudioElement).currentTime - (element as HTMLAudioElement).duration,
            ),
          ),
      )
      .toBeLessThan(0.1)
    await player.getByRole('button', { name: '后退 10 秒', exact: true }).click()
    await expect
      .poll(() =>
        page.locator('audio').evaluate((element) => (element as HTMLAudioElement).currentTime),
      )
      .toBe(0)
    const speed = player.getByLabel('播放倍速', { exact: true })
    await speed.click()
    const trigger = await speed.boundingBox()
    for (const option of await speed.getByRole('option').all()) {
      const bounds = await option.boundingBox()
      expect(bounds).not.toBeNull()
      expect(bounds!.y).toBeGreaterThanOrEqual(0)
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(
        (await page.evaluate(() => innerHeight)) + 1,
      )
      expect(Math.abs(bounds!.x - trigger!.x)).toBeLessThan(24)
    }
    await speed.press('Escape')
    await expect(speed).toBeFocused()
    await speed.selectOption('1.5')
    expect(
      await page.locator('audio').evaluate((element) => (element as HTMLAudioElement).playbackRate),
    ).toBe(1.5)
    await player.getByRole('button', { name: '静音', exact: true }).click()
    expect(
      await page.locator('audio').evaluate((element) => (element as HTMLAudioElement).muted),
    ).toBe(true)
    await player.focus()
    await player.press('m')
    expect(
      await page.locator('audio').evaluate((element) => (element as HTMLAudioElement).muted),
    ).toBe(false)
    const rows = await page.evaluate(() => window.paa.listMeetings())
    expect(rows.ok && rows.meetings[0].audioAvailable).toBe(true)
    expect(rows.ok && Object.hasOwn(rows.meetings[0], 'audioPath')).toBe(false)
    await page.getByRole('button', { name: '返回会议列表', exact: true }).click()
    await expect(player).toHaveCount(0)
    await expect(page.locator('audio')).toHaveCount(0)
    await page.locator('.meeting-row').click()
    await page.waitForTimeout(1200)
    await expect(player).toHaveCount(1)
    await page.getByRole('button', { name: '返回会议列表', exact: true }).click()
    await expect(player).toHaveCount(0)
    await expect(page.locator('audio')).toHaveCount(0)
    // Ending immediately must leave the current-meeting route even before a poll sees recording.
    await page.getByRole('button', { name: '开始会议', exact: true }).click()
    await page.getByRole('button', { name: '结束会议', exact: true }).click()
    await expect(page.getByRole('region', { name: '会议工作区', exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: '纪要', exact: true })).toHaveAttribute(
      'aria-selected',
      'true',
    )
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
  const testInfo = test.info()
  const started = Date.now()
  const stages: { stage: string; elapsedMs: number; error?: string }[] = []
  const stagePath = testInfo.outputPath('save-failure-stages.json')
  mkdirSync(dirname(stagePath), { recursive: true })
  const record = (stage: string, error?: unknown): void => {
    stages.push({
      stage,
      elapsedMs: Date.now() - started,
      error: error === undefined ? undefined : String(error),
    })
    writeFileSync(stagePath, JSON.stringify(stages, null, 2))
  }
  record('launch')
  const app = await launch(temp(), true, { PAA_FIXTURE_FAIL_CLOSE: '1' })
  let cleanupFailure: unknown
  try {
    record('ready')
    const page = await ready(app)
    record('start recording')
    await page.getByRole('button', { name: '开始会议', exact: true }).click()
    await expect.poll(() => recordingState(app)).toBe('recording')
    await page.waitForTimeout(150)
    await app.evaluate(({ dialog }) => {
      dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
    })
    record('request close with save failure')
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    record('verify save protection')
    await expect.poll(() => recordingState(app)).toBe('interrupted')
    await expect(page.getByRole('alert')).toContainText('保存失败')
    expect(
      await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()),
    ).toBe(true)
    const result = await page.evaluate(() => window.paa.listMeetings())
    expect(result.ok && result.meetings[0].audioAvailable).toBe(true)
    record('save protection passed')
  } finally {
    const child = app.process()
    if (child.exitCode === null && child.signalCode === null) {
      record('cleanup')
      try {
        // Keep the main debugger connected until the asynchronous exit guard finishes.
        await Promise.all([
          app.waitForEvent('close', { timeout: 10_000 }),
          app.evaluate(({ BrowserWindow, dialog }) => {
            dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
            BrowserWindow.getAllWindows()[0]?.close()
          }),
        ])
        record('cleanup completed')
      } catch (error) {
        record('cleanup failed', error)
        cleanupFailure = error
        if (child.exitCode === null && child.signalCode === null) {
          try {
            child.kill('SIGKILL')
          } catch (terminationError) {
            record('cleanup termination failed', terminationError)
          }
        }
      }
    }
  }
  // Preserve a body error; unsuccessful cleanup must also fail an otherwise passing test.
  if (cleanupFailure) throw cleanupFailure
})

test('missing Python opens the desktop and supports retry', async () => {
  const app = await launch(temp(), false, { PAA_PYTHON: resolve('artifacts/missing-python') })
  try {
    const page = await app.firstWindow()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('error')
    await page.getByRole('button', { name: '模型服务管理', exact: true }).click()
    await expect(page.getByRole('button', { name: '重新连接', exact: true })).toBeEnabled()
  } finally {
    await app.close()
  }
})
