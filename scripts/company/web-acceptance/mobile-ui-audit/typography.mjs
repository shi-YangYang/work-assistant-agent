// Manual Spec073 text-only magnification audit; never changes product files.
import { chromium } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { isolatedEnvironment } from '../../../../tests/e2e/web/fixtures/environment.mjs'

const state = isolatedEnvironment()
const runRoot = resolve(process.env.SPEC073_RUN_ROOT)
const records = JSON.parse(await readFile(resolve(runRoot, 'environment/layout.json'), 'utf8'))
const output = resolve(runRoot, 'typography')
await mkdir(output, { recursive: true })
const rows = []
const browser = await chromium.launch()
const click = (name) => async (page) => page.getByRole('button', { name, exact: true }).click()
const cases = [
  { name: 'navigation', route: '/work', open: click('展开导航') },
  {
    name: 'settings-navigation',
    route: '/work',
    open: async (page) => {
      await click('展开导航')(page)
      await click('系统设置')(page)
    },
  },
  { name: 'work-list', route: '/work' },
  { name: 'work-create', route: '/work', open: click('新建工作') },
  { name: 'work-detail', route: `/work/${records.employee.work}` },
  { name: 'report-detail', route: `/reports/${records.employee.weekly}` },
  { name: 'report-editor', route: `/reports/${records.employee.weekly}`, open: click('编辑草稿') },
  { name: 'account', route: '/settings/account' },
  { name: 'rules', route: '/settings/rules' },
]

try {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  })
  const login = await context.newPage()
  await login.goto(state.origin)
  await login.waitForLoadState('networkidle')
  const direct = login.getByRole('button', { name: /直接登录/ })
  if (await direct.count()) await direct.click()
  await login.getByLabel('账号', { exact: true }).fill(state.users.employee.username)
  await login.getByLabel('密码', { exact: true }).fill(state.users.employee.password)
  await login.getByRole('button', { name: '登录', exact: true }).click()
  await login
    .getByRole('navigation', { name: '工作空间', includeHidden: true })
    .waitFor({ state: 'attached' })
  await login.close()
  for (const item of cases) {
    const page = await context.newPage()
    page.setDefaultTimeout(7000)
    const row = {
      caseId: 'S07',
      name: item.name,
      role: 'employee',
      route: item.route,
      viewport: { width: 390, height: 844 },
      browser: 'chromium',
      theme: 'light',
      dataMode: 'isolated-api',
      method:
        'All computed font sizes and numeric line heights doubled after UI opens; text-only simulation, not native phone font setting.',
      reviewedBy: null,
      visualVerdict: 'PENDING',
      notes: [],
    }
    try {
      await page.goto(state.origin + item.route)
      await page.waitForLoadState('networkidle')
      if (item.open) await item.open(page)
      await page.evaluate(async () => {
        await document.fonts.ready
        const styles = [...document.querySelectorAll('body, body *')].map((element) => {
          const style = getComputedStyle(element)
          return [element, parseFloat(style.fontSize), style.lineHeight]
        })
        // Snapshot before writing so inherited values are not multiplied twice.
        for (const [element, fontSize, lineHeight] of styles) {
          element.style.setProperty('font-size', `${fontSize * 2}px`, 'important')
          if (lineHeight !== 'normal')
            element.style.setProperty('line-height', `${parseFloat(lineHeight) * 2}px`, 'important')
        }
      })
      await page.waitForTimeout(150)
      row.metrics = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth - innerWidth,
        controls: [...document.querySelectorAll('button,a,input,textarea,[role=dialog]')]
          .map((element) => {
            const rect = element.getBoundingClientRect()
            return {
              name: (element.getAttribute('aria-label') || element.textContent || '')
                .trim()
                .slice(0, 100),
              x: rect.x,
              y: rect.y,
              width: rect.width,
              height: rect.height,
              scrollWidth: element.scrollWidth,
              clientWidth: element.clientWidth,
            }
          })
          .filter(
            (item) =>
              item.width > 0 && item.height > 0 && item.y < innerHeight && item.y + item.height > 0,
          ),
      }))
      row.result = 'CAPTURED'
    } catch (error) {
      row.result = 'BLOCKED'
      row.error = error.message
    }
    row.evidence = `${item.name}-390x844-text200.png`
    await page.screenshot({ path: resolve(output, row.evidence) })
    rows.push(row)
    await writeFile(resolve(output, 'screenshot-index.json'), JSON.stringify(rows, null, 2))
    await page.close({ runBeforeUnload: false })
  }
  await context.close()
} finally {
  await browser.close()
}
