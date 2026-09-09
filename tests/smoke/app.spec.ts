import { _electron as electron, expect, test, type ElectronApplication } from '@playwright/test'
import { mkdirSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

mkdirSync('artifacts', { recursive: true })

async function launch(extraEnv: Record<string, string> = {}): Promise<ElectronApplication> {
  const env: Record<string, string> = Object.fromEntries(
    Object.entries({ ...process.env, ...extraEnv }).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string',
    ),
  )
  delete env.ELECTRON_RUN_AS_NODE
  delete env.ELECTRON_RENDERER_URL
  return electron.launch({ args: [resolve('.')], env })
}

test('real desktop connects, stays isolated, survives core exit and cleans up on close', async () => {
  const app = await launch()
  let currentPid: number | undefined
  try {
    const page = await app.firstWindow()
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await expect(page.getByRole('heading', { name: '留住讨论，理清下一步。' })).toBeVisible()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('ready')
    const status = await page.evaluate(() => window.paa.getStatus())
    currentPid = status.processId
    expect(status.capabilities.every((capability) => !capability.available)).toBe(true)
    await expect(page.getByRole('button', { name: '开始会议' })).toBeDisabled()
    await expect(page.getByText('录音功能尚未接入')).toBeVisible()
    await expect(page.getByText('暂无会议记录', { exact: true })).toBeVisible()
    expect(
      await page.evaluate(() => ({ node: typeof process, require: typeof window.require })),
    ).toEqual({ node: 'undefined', require: 'undefined' })
    const sandboxed = await app.evaluate(({ app, BrowserWindow }) => {
      const rendererPid = BrowserWindow.getAllWindows()[0].webContents.getOSProcessId()
      return app.getAppMetrics().find((metric) => metric.pid === rendererPid)?.sandboxed
    })
    expect(sandboxed).toBe(true)
    const csp = await page
      .locator('meta[http-equiv="Content-Security-Policy"]')
      .getAttribute('content')
    expect(csp).toContain("script-src 'self';")
    expect(csp).not.toContain('unsafe-inline')
    await page.screenshot({ path: 'artifacts/meeting-workspace.png' })
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await expect(page.getByRole('heading', { name: '本地核心', exact: true })).toBeVisible()
    await expect(page.getByText(`Python ${status.pythonVersion}`, { exact: false })).toBeVisible()
    await page.screenshot({ path: 'artifacts/settings-ready.png' })

    process.kill(currentPid!)
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('error')
    await expect(page.getByText('本地核心已退出，请重新连接。', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '重新连接' }).click()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('ready')
    currentPid = (await page.evaluate(() => window.paa.getStatus())).processId

    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(900, 640))
    await page.getByRole('button', { name: '会议记录', exact: true }).click()
    await expect(page.getByRole('button', { name: '开始会议' })).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.screenshot({ path: 'artifacts/meeting-minimum.png' })
    await page.getByRole('heading', { name: '从对话，到行动' }).scrollIntoViewIfNeeded()
    await expect(page.getByText('待接入 · 会议纪要', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await page.getByRole('button', { name: '重新连接' }).scrollIntoViewIfNeeded()
    await expect(page.getByRole('button', { name: '重新连接' })).toBeVisible()
    expect(errors).toEqual([])

    const closed = app.waitForEvent('close')
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    await closed
    expect(() => process.kill(currentPid!, 0)).toThrow()
  } finally {
    await app.close().catch(() => {})
  }
})

test('missing Python still opens the full desktop and exposes retry', async () => {
  const app = await launch({ PAA_PYTHON: resolve('artifacts/missing-python') })
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('heading', { name: '留住讨论，理清下一步。' })).toBeVisible()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('error')
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await expect(
      page.getByText('未找到 Python 3.12。请创建项目 .venv 或设置 PAA_PYTHON 后重试。', {
        exact: true,
      }),
    ).toBeVisible()
    await page.getByRole('button', { name: '重新连接' }).click()
    await expect(page.getByRole('button', { name: '重新连接' })).toBeEnabled()
    await page.screenshot({ path: 'artifacts/core-unavailable.png' })
  } finally {
    await app.close()
  }
})

test('older macOS system Python produces the explicit version guidance', async () => {
  test.skip(
    process.platform !== 'darwin' ||
      !existsSync('/usr/bin/python3') ||
      spawnSync('/usr/bin/python3', ['--version'], { encoding: 'utf8' }).stdout.startsWith(
        'Python 3.12.',
      ),
    'Only applicable when macOS system Python differs from the project baseline',
  )
  const app = await launch({ PAA_PYTHON: '/usr/bin/python3' })
  try {
    const page = await app.firstWindow()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('error')
    const status = await page.evaluate(() => window.paa.getStatus())
    expect(status.message).toBe('本地核心需要 Python 3.12，请更新项目 .venv 后重试。')
  } finally {
    await app.close()
  }
})
