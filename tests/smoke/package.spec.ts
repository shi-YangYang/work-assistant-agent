import { test, expect, _electron as electron } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

test('installed package starts its bundled core without Python, Node or source cwd', async () => {
  test.skip(
    process.env.CI !== 'true' || process.env.PAA_PACKAGE_SMOKE !== '1',
    'Installer fixtures run only in CI; local acceptance uses the daily app',
  )
  test.setTimeout(180_000)
  const root = mkdtempSync(join(tmpdir(), 'paa-install-'))
  let mounted = false
  const mount = join(root, 'mount')
  const install = join(root, '安装包 App')
  const data = join(root, 'data')
  const errors: unknown[] = []
  mkdirSync(install)
  async function cleanup(action: () => void | Promise<void>): Promise<void> {
    try {
      await action()
    } catch (error) {
      errors.push(error)
    }
  }
  function run(command: string, args: string[], timeout = 90_000): void {
    const result = spawnSync(command, args, {
      encoding: 'utf8',
      timeout,
      windowsHide: true,
    })
    if (result.error) throw result.error
    expect(result.status, `${command}\n${result.stderr}`).toBe(0)
  }
  try {
    const directory = resolve('dist/desktop')
    const artifact = readdirSync(directory).find((name) =>
      name.endsWith(process.platform === 'darwin' ? '.dmg' : '.exe'),
    )!
    expect(artifact).toBeTruthy()
    let executable: string
    if (process.platform === 'darwin') {
      mkdirSync(mount)
      run('/usr/bin/hdiutil', [
        'attach',
        join(directory, artifact),
        '-nobrowse',
        '-mountpoint',
        mount,
      ])
      mounted = true
      run('/usr/bin/ditto', [join(mount, '个人工作助手.app'), join(install, '个人工作助手.app')])
      run('/usr/bin/hdiutil', ['detach', mount])
      mounted = false
      executable = join(install, '个人工作助手.app/Contents/MacOS/个人工作助手')
    } else {
      // NSIS's /D argument must be last and unquoted; this CI-generated path has no spaces.
      const windowsInstall = join(root, 'installed')
      run(join(directory, artifact), ['/S', `/D=${windowsInstall}`])
      executable = join(windowsInstall, '个人工作助手.exe')
    }
    expect(existsSync(executable)).toBe(true)
    const env = Object.fromEntries(
      Object.entries({
        ...process.env,
        PATH: root,
        PAA_PYTHON: join(root, 'absent-python'),
        PAA_TEST_DATA_DIR: data,
        ELECTRON_RENDERER_URL: 'https://must-not-load.invalid',
      }).filter((entry): entry is [string, string] => typeof entry[1] === 'string'),
    )
    delete env.ELECTRON_RUN_AS_NODE
    const app = await electron.launch({
      executablePath: executable,
      args: [],
      cwd: root,
      env,
      timeout: 30_000,
    })
    try {
      const page = await app.firstWindow()
      const appPath = await app.evaluate(({ app }) => app.getAppPath())
      await expect(page).toHaveURL(pathToFileURL(join(appPath, 'out/renderer/index.html')).href)
      await expect
        .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection, {
          timeout: 30_000,
        })
        .toBe('ready')
      expect(await app.evaluate(({ app }) => app.isPackaged)).toBe(true)
      const status = await page.evaluate(() => window.paa.getStatus())
      expect(status.pythonVersion).toMatch(/^3\.12\./)
      expect(status.capabilities.find((entry) => entry.id === 'recording')?.available).toBe(true)
      await page.getByRole('button', { name: '设置', exact: true }).click()
      await expect(page.getByRole('heading', { name: '应用状态', exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: '模型服务管理', exact: true })).toHaveAttribute(
        'aria-expanded',
        'false',
      )
      await page.getByRole('button', { name: '重新连接', exact: true }).click()
      await expect
        .poll(
          async () => {
            const current = await page.evaluate(() => window.paa.getStatus())
            return (
              current.connection === 'ready' &&
              typeof current.processId === 'number' &&
              current.processId !== status.processId
            )
          },
          { timeout: 30_000 },
        )
        .toBe(true)
      await expect(page.getByRole('button', { name: '重新连接', exact: true })).toBeEnabled()
      mkdirSync('artifacts/spec005', { recursive: true })
      await page.screenshot({ path: `artifacts/spec005/installed-${process.platform}.png` })
    } finally {
      const child = app.process()
      await cleanup(() =>
        test.step('close installed app', async () => {
          if (child.exitCode !== null || child.signalCode !== null) return
          // Keep the main debugger connected until the asynchronous exit guard finishes.
          await Promise.all([
            app.waitForEvent('close', { timeout: 10_000 }),
            app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close()),
          ])
        }),
      )
      await cleanup(() => {
        // A failed graceful exit still fails the test; only terminate this test's process tree.
        if (child.exitCode !== null || child.signalCode !== null || !child.pid) return
        if (process.platform === 'win32')
          run('taskkill', ['/PID', String(child.pid), '/T', '/F'], 10_000)
        else child.kill('SIGKILL')
      })
    }
  } catch (error) {
    // Keep the original launch/assertion error ahead of any teardown failures.
    errors.unshift(error)
  } finally {
    if (mounted) await cleanup(() => run('/usr/bin/hdiutil', ['detach', mount], 30_000))
    await cleanup(() => {
      if (process.platform !== 'win32') return
      const windowsInstall = join(root, 'installed')
      const uninstall = join(windowsInstall, 'Uninstall 个人工作助手.exe')
      if (!existsSync(uninstall)) return
      // NSIS otherwise starts a temporary copy and returns before uninstall completes.
      // Run our own copy outside the install directory; _?= must be last and unquoted.
      const runner = join(root, 'uninstall.exe')
      copyFileSync(uninstall, runner)
      run(runner, ['/S', `_?=${windowsInstall}`], 30_000)
    })
    await cleanup(() =>
      rmSync(root, {
        recursive: true,
        force: true,
        maxRetries: process.platform === 'win32' ? 5 : 0,
        retryDelay: 200,
      }),
    )
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1)
    throw new AggregateError(errors, 'Installed package test or cleanup failed', {
      cause: errors[0],
    })
})
