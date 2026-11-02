// Explicit Spec068 screenshot audit against an ownership-verified disposable API.
import { chromium } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { isolatedEnvironment } from '../../../../tests/e2e/web/fixtures/environment.mjs'
import { api } from '../../../../eval/web/agent-browser-common.mjs'
const state = isolatedEnvironment()
if (!process.env.SPEC068_OUTPUT) throw new Error('Unique evidence output required')
const output = resolve(process.env.SPEC068_OUTPUT)
const ids = JSON.parse(await readFile(process.env.UI_LAYOUT_RECORDS, 'utf8'))
await mkdir(output, { recursive: true })
const results = []
const browser = await chromium.launch()
const click = (name) => async (page) => {
  const tab = page.getByRole('tab', { name, exact: true })
  await ((await tab.count()) ? tab : page.getByRole('button', { name, exact: true })).click()
}
const common = (role) => [
  ['assistant-new', '/assistant?new=1'],
  ['assistant-history', `/assistant/${ids[role].conversation}`],
  ['source', `/messages/${ids[role].message}`],
  ['work', '/work'],
  ['work-detail', `/work/${ids[role].work}`],
  ['work-history', `/work/${ids[role].work}?revision=1`],
  ['work-create', '/work', click('新建工作')],
  ['work-content-editor', `/work/${ids[role].work}`, click('编辑内容')],
  ['account-info', '/settings/account'],
  ['appearance-compatibility', '/settings/appearance'],
  ['memory', '/settings/memory'],
  ['memory-editor', '/settings/memory', click('编辑')],
  ['rules', '/settings/rules'],
  ['feedback-submit', '/settings/support'],
  ['feedback-records', '/settings/support', click('反馈记录')],
  ['notifications-reminders', '/notifications?tab=reminders'],
  ['notifications-announcements', '/notifications?tab=announcements'],
  ['announcement-detail', () => `/notifications/announcements/${ids.announcement}`],
  ['desktop-connect-invalid', '/desktop/connect?request=invalid'],
  ['missing-source', '/messages/missing-source'],
  ['missing-work', '/work/missing-work'],
  ['missing-report', '/reports/missing-report'],
]
const admin = [
  ['team-work', '/team'],
  ['team-updated', '/team?scope=updated'],
  ['team-weekly', '/team?view=reports'],
  ['team-work-drawer', () => `/team?record=${ids.employee.work}`],
  ['team-report-drawer', () => `/team?view=reports&record=${ids.employee.weekly}`],
  ['members', '/members'],
  ['member-create', '/members', click('添加成员')],
  ['announcements', '/announcement-management'],
  ['announcement-new', '/announcement-management/new'],
  ['announcement-management-detail', () => `/announcement-management/${ids.announcement}`],
  ['announcement-edit', () => `/announcement-management/${ids.announcement}/edit`],
  ['account-password', '/settings/account', click('修改密码')],
  ['account-dingtalk', '/settings/account', click('钉钉账号关联')],
  ['rules-weekly', '/settings/rules', click('周报')],
  ['models', '/settings/models'],
  ['models-routing', '/settings/models', click('用途分配')],
  ['usage', '/settings/usage'],
  ['voiceprints', '/settings/voiceprints'],
  ['login-credentials', '/settings/login'],
  ['login-authorization', '/settings/login', click('授权与入口')],
  ['login-setup', '/settings/login', click('钉钉后台配置')],
  ['report-detail', () => `/reports/${ids.employee.weekly}`],
  ['team-legacy-details', '/team/details'],
  ['team-legacy-reports', '/team/reports'],
]
const employee = [
  ['reports-todo', '/reports'],
  ['reports-weekly', '/reports', click('全部报告')],
  ['report-detail', () => `/reports/${ids.employee.weekly}`],
  ['report-draft', () => `/reports/${ids.employee.draft}`],
  ['report-edit', () => `/reports/${ids.employee.draft}`, click('编辑草稿')],
  ['reports-schedule', '/reports', click('汇报安排')],
]
const filter = process.env.UI_AUDIT_FILTER?.split(',')
async function ready(page) {
  await page
    .getByRole('navigation', { name: /工作空间|系统设置/, includeHidden: true })
    .waitFor({ state: 'attached' })
  await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {})
  await page.evaluate(() => document.fonts.ready)
}
async function metrics(page) {
  return page.evaluate(() => {
    const visible = (n) => {
      const r = n.getBoundingClientRect()
      return !!(r.width && r.height) && getComputedStyle(n).visibility !== 'hidden'
    }
    const rect = (n) => {
      const r = n.getBoundingClientRect()
      return {
        text: (n.getAttribute('aria-label') || n.textContent || '').trim().slice(0, 70),
        x: r.x,
        y: r.y,
        width: r.width,
        height: r.height,
      }
    }
    return {
      viewport: [innerWidth, innerHeight],
      overflow: document.documentElement.scrollWidth - innerWidth,
      headings: [...document.querySelectorAll('h1,h2,h3')].filter(visible).map(rect),
      alerts: [...document.querySelectorAll('[role=alert]')].filter(visible).map(rect),
      dialogs: [...document.querySelectorAll('dialog[open],[role=dialog]')]
        .filter(visible)
        .map(rect),
      scrollers: [...document.querySelectorAll('[data-scroll-container]')]
        .filter(visible)
        .map((n) => ({ ...rect(n), scrollHeight: n.scrollHeight, clientHeight: n.clientHeight })),
    }
  })
}
async function shot(page, role, item, size, theme) {
  const [name, path, action] = item
  const file = `${role}--${name}--${size.name}-${theme}.png`
  const row = {
    id: `W-${role}-${name}-${size.name}-${theme}`,
    role,
    case: name,
    path: typeof path === 'function' ? path() : path,
    viewport: size,
    theme,
    file,
    source: 'owned-api',
    status: 'PASS',
    visualReview: 'PENDING',
  }
  const errors = []
  const onError = (e) => errors.push(e.message)
  page.on('pageerror', onError)
  try {
    await page.setViewportSize({ width: size.width, height: size.height })
    await page.evaluate((value) => localStorage.setItem('paa.company.theme', value), theme)
    await page.goto(state.origin + row.path)
    await ready(page)
    if (action) await action(page)
    await page.waitForTimeout(150)
    row.metrics = await metrics(page)
    if (row.metrics.alerts.some((a) => a.text.includes('页面未能加载'))) row.status = 'BLOCKED'
    if (row.metrics.overflow > 1) row.status = 'FAIL'
    if (errors.length) row.status = 'FAIL'
    await page.screenshot({ path: resolve(output, file), animations: 'disabled' })
  } catch (e) {
    row.status = 'BLOCKED'
    row.error = e.message
    await page.screenshot({ path: resolve(output, file), animations: 'disabled' }).catch(() => {})
  }
  row.errors = errors
  page.off('pageerror', onError)
  results.push(row)
  await writeFile(resolve(output, 'index.json'), JSON.stringify(results, null, 2))
  console.log(`${row.status} ${file}`)
}
try {
  for (const role of ['admin', 'employee']) {
    const context = await browser.newContext({
      locale: 'zh-CN',
      timezoneId: 'Asia/Shanghai',
      reducedMotion: 'reduce',
    })
    const page = await context.newPage()
    page.setDefaultTimeout(7000)
    await page.goto(state.origin)
    await page.getByRole('button', { name: /直接登录/ }).click()
    await page.getByLabel('账号', { exact: true }).fill(state.users[role].username)
    await page.getByLabel('密码', { exact: true }).fill(state.users[role].password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await ready(page)
    if (role === 'admin' && !ids.announcement) {
      const a = await api(page, '/api/v1/announcements', 'POST', {
        title: 'Spec068 合成公告：页面验收安排',
        markdown:
          '# 合成通知\n\n请核对手机与电脑页面。\n\n- 时间：2026-10-13\n- **仅测试数据**，无需实际操作。',
      })
      ids.announcement = a.id
      await writeFile(process.env.UI_LAYOUT_RECORDS, JSON.stringify(ids, null, 2))
    }
    const cases = [...common(role), ...(role === 'admin' ? admin : employee)].filter(
      (c) => !filter || filter.includes(c[0]),
    )
    for (const item of cases)
      for (const size of [
        { name: 'desktop', width: 1440, height: 900 },
        { name: 'mobile', width: 390, height: 844 },
      ])
        for (const theme of ['light', 'dark']) await shot(page, role, item, size, theme)
    await context.close()
  }
} finally {
  await browser.close()
}
