import { test, expect, _electron as electron } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

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
  mkdirSync(install)
  function run(command: string, args: string[]): void {
    const result = spawnSync(command, args, {
      encoding: 'utf8',
      timeout: 90_000,
      windowsHide: true,
    })
    expect(result.status, `${result.error?.message || ''}\n${result.stderr}`).toBe(0)
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
      await expect
        .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection, {
          timeout: 30_000,
        })
        .toBe('ready')
      expect(await app.evaluate(({ app }) => app.isPackaged)).toBe(true)
      expect(page.url()).toMatch(/^file:/)
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
        .poll(async () => (await page.evaluate(() => window.paa.getStatus())).processId)
        .not.toBe(status.processId)
      mkdirSync('artifacts/spec005', { recursive: true })
      await page.screenshot({ path: `artifacts/spec005/installed-${process.platform}.png` })
    } finally {
      await app.close()
    }
  } finally {
    if (mounted) spawnSync('/usr/bin/hdiutil', ['detach', mount], { timeout: 30_000 })
    if (process.platform === 'win32') {
      const uninstall = join(root, 'installed', 'Uninstall 个人工作助手.exe')
      if (existsSync(uninstall))
        spawnSync(uninstall, ['/S'], { timeout: 30_000, windowsHide: true })
    }
    rmSync(root, { recursive: true, force: true })
  }
})
