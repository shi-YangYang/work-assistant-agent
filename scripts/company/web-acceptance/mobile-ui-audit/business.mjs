// Manual Spec073 mobile audit. Product code stays untouched; every write uses an owned API.
import { chromium, webkit, expect } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { api } from '../../../../eval/web/agent-browser-common.mjs'
import { isolatedEnvironment } from '../../../../tests/e2e/web/fixtures/environment.mjs'
const state = isolatedEnvironment()
const output = resolve(
  process.env.SPEC073_OUTPUT || 'artifacts/spec073/20261017-015130-b9afe2a/business',
)
const ids = JSON.parse(await readFile(process.env.UI_LAYOUT_RECORDS, 'utf8'))
await mkdir(output, { recursive: true })
const index = [],
  flows = [],
  errors = []
const run = process.env.BUSINESS_RUN || 'baseline'
const button = (name) => async (p) => p.getByRole('button', { name, exact: true }).first().click()
const tab = (name) => async (p) => p.getByRole('tab', { name, exact: true }).click()
const sequence =
  (...actions) =>
  async (p) => {
    for (const action of actions) await action(p)
  }
const more = (menu, item) =>
  sequence(button(menu), async (p) => p.getByRole('menuitem', { name: item, exact: true }).click())
const item = (id, name, route, action, extra = {}) => ({ id, name, route, action, ...extra })
const supplemental = resolve(output, 'business-records.json')
try {
  Object.assign(ids, JSON.parse(await readFile(supplemental, 'utf8')))
} catch {
  // The first audit run has no supplemental fixture IDs yet.
}
if (!ids.announcement) {
  const browser = await chromium.launch()
  try {
    const { context, p } = await login(browser, 'admin')
    const a = await api(p, '/api/v1/announcements', 'POST', {
      title: '手机界面审阅：长标题公告与多端协作安排，仅为合成数据',
      markdown:
        '# 手机界面验收\n\n' +
        Array.from(
          { length: 12 },
          (_, i) => `## 第 ${i + 1} 项\n\n请核对导航、字体和操作位置。仅为合成测试，无需员工执行。`,
        ).join('\n\n'),
    })
    ids.announcement = a.id
    await writeFile(supplemental, JSON.stringify({ announcement: a.id }, null, 2))
    await context.close()
  } finally {
    await browser.close()
  }
}
const common = (role) => [
  item('M07', 'source', `/messages/${ids[role].message}`),
  item('M08', 'work', '/work'),
  item('M08', 'work-create', '/work', button('新建工作'), { modal: true }),
  item('M09', 'work-detail', `/work/${ids[role].work}`, null, { long: true }),
  item('M09', 'work-history', `/work/${ids[role].work}?revision=1`),
  item('M09', 'work-editor', `/work/${ids[role].work}`, button('编辑内容'), { long: true }),
  item('M09', 'work-properties', `/work/${ids[role].work}`, more('管理工作', '编辑工作属性'), {
    modal: true,
  }),
  item('M09', 'work-delete', `/work/${ids[role].work}`, more('管理工作', '删除工作'), {
    modal: true,
  }),
  item('M15', 'account', '/settings/account', null, { long: true }),
  item('M20', 'memory', '/settings/memory'),
  item('M20', 'memory-editor', '/settings/memory', button('编辑')),
  item('M16', 'rules', '/settings/rules', null, { long: true }),
  item('M22', 'feedback-submit', '/settings/support', null, { long: true }),
  item('M22', 'feedback-records', '/settings/support', tab('反馈记录')),
  item('M13', 'notifications-reminders', '/notifications?tab=reminders'),
  item('M13', 'notifications-announcements', '/notifications?tab=announcements'),
  ...(ids.announcement
    ? [
        item(
          'M13',
          'announcement-detail',
          `/notifications/announcements/${ids.announcement}`,
          null,
          { long: true },
        ),
      ]
    : []),
  item('M23', 'appearance', '/settings/appearance'),
  item('M01', 'desktop-invalid', '/desktop/connect?request=invalid'),
  item('M24', 'missing-source', '/messages/missing-source'),
  item('M24', 'missing-work', '/work/missing-work'),
  item('M24', 'missing-report', '/reports/missing-report'),
  item('M02', 'main-navigation', '/work', button('展开导航'), { modal: true }),
  item('M02', 'settings-navigation', '/work', sequence(button('展开导航'), button('系统设置')), {
    modal: true,
  }),
  item('M02', 'command-search', '/work', sequence(button('展开导航'), button('查找页面与操作')), {
    modal: true,
  }),
]
const administrators = [
  item('M11', 'team-work', '/team'),
  item('M11', 'team-updated', '/team?scope=updated'),
  item('M11', 'team-weekly', '/team?view=reports'),
  item('M11', 'team-work-detail', `/team?record=${ids.employee.work}`, null, { modal: true }),
  item('M11', 'team-report-detail', `/team?view=reports&record=${ids.employee.weekly}`, null, {
    modal: true,
  }),
  item('M12', 'members', '/members'),
  item('M12', 'member-create', '/members', button('添加成员'), { modal: true }),
  item('M12', 'member-actions', '/members', button('更多操作'), { modal: true }),
  item('M14', 'announcements', '/announcement-management'),
  item('M14', 'announcement-new', '/announcement-management/new', null, { long: true }),
  ...(ids.announcement
    ? [
        item(
          'M14',
          'announcement-management-detail',
          `/announcement-management/${ids.announcement}`,
          null,
          { long: true },
        ),
        item(
          'M14',
          'announcement-edit',
          `/announcement-management/${ids.announcement}/edit`,
          null,
          { long: true },
        ),
        item('M14', 'announcement-delete', '/announcement-management', button('删除'), {
          modal: true,
        }),
      ]
    : []),
  item('M15', 'account-password', '/settings/account', tab('修改密码')),
  item('M15', 'account-dingtalk', '/settings/account', tab('钉钉账号关联')),
  item('M16', 'rules-weekly', '/settings/rules', tab('周报'), { long: true }),
  item('M18', 'models', '/settings/models', null, { long: true }),
  item('M18', 'models-routing', '/settings/models', tab('用途分配'), { long: true }),
  item('M18', 'model-new', '/settings/models', button('添加服务'), { long: true }),
  item('M19', 'usage', '/settings/usage', null, { long: true }),
  item('M21', 'voiceprints', '/settings/voiceprints', null, { long: true }),
  item('M21', 'voiceprint-enrollment', '/settings/voiceprints', button('上传录音'), {
    modal: true,
  }),
  item('M17', 'login-credentials', '/settings/login', null, { long: true }),
  item('M17', 'login-authorization', '/settings/login', tab('授权与入口'), { long: true }),
  item('M17', 'login-setup', '/settings/login', tab('钉钉后台配置'), { long: true }),
  item('M10', 'admin-report-detail', `/reports/${ids.employee.weekly}`, null, { long: true }),
  item('M24', 'team-legacy-details', '/team/details'),
  item('M24', 'team-legacy-reports', '/team/reports'),
  item('M24', 'team-legacy-member', `/team/${state.users.employee.id}`),
]
const employees = [
  item('M10', 'reports-todo', '/reports'),
  item('M10', 'reports-weekly', '/reports', button('全部报告')),
  item('M10', 'report-published', `/reports/${ids.employee.weekly}`, null, { long: true }),
  item('M10', 'report-draft', `/reports/${ids.employee.draft}`, null, { long: true }),
  item('M10', 'report-edit', `/reports/${ids.employee.draft}`, button('编辑草稿'), { long: true }),
  item('M10', 'report-submit', `/reports/${ids.employee.draft}`, button('提交报告'), {
    modal: true,
  }),
  item('M10', 'report-delete', `/reports/${ids.employee.weekly}`, more('管理报告', '删除报告'), {
    modal: true,
  }),
  item('M10', 'reports-schedule', '/reports', button('汇报安排'), { long: true }),
  item('M24', 'employee-admin-denied', '/members'),
  item('M24', 'settings-unknown', '/settings/does-not-exist'),
  item('M24', 'unknown-route', '/not-a-route'),
]
async function ready(p) {
  await p.waitForLoadState('domcontentloaded')
  await p.waitForLoadState('networkidle', { timeout: 2500 }).catch(() => {})
  await p.evaluate(() => document.fonts.ready)
  await p.waitForTimeout(100)
}
async function login(browser, role, size = { width: 390, height: 844 }) {
  const context = await browser.newContext({
    viewport: size,
    isMobile: true,
    hasTouch: true,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  })
  const p = await context.newPage()
  p.setDefaultTimeout(5000)
  p.on('pageerror', (e) => errors.push({ role, url: p.url(), error: e.message }))
  p.on('dialog', async (d) => {
    errors.push({ role, url: p.url(), nativeDialog: d.type(), message: d.message() })
    if (d.type() === 'beforeunload') await d.accept()
    else await d.dismiss()
  })
  await p.goto(state.origin)
  await ready(p)
  const direct = p.getByRole('button', { name: /直接登录/ })
  if (await direct.count()) await direct.click()
  await p.getByLabel('账号', { exact: true }).fill(state.users[role].username)
  await p.getByLabel('密码', { exact: true }).fill(state.users[role].password)
  await p.getByRole('button', { name: '登录', exact: true }).click()
  await p
    .getByRole('navigation', { name: '工作空间', includeHidden: true })
    .waitFor({ state: 'attached' })
  await ready(p)
  return { context, p }
}
async function metrics(p) {
  return p.evaluate(() => {
    const visible = (n) => {
      const r = n.getBoundingClientRect()
      return r.width > 0 && r.height > 0 && getComputedStyle(n).visibility !== 'hidden'
    }
    const rect = (n) => {
      const r = n.getBoundingClientRect()
      return {
        text: (n.getAttribute('aria-label') || n.textContent || '').trim().slice(0, 80),
        x: Math.round(r.x),
        y: Math.round(r.y),
        width: Math.round(r.width),
        height: Math.round(r.height),
      }
    }
    return {
      overflow: document.documentElement.scrollWidth - innerWidth,
      headings: [...document.querySelectorAll('h1,h2,h3')].filter(visible).map(rect),
      dialogs: [...document.querySelectorAll('dialog[open],[role=dialog]')]
        .filter(visible)
        .map(rect),
      alerts: [...document.querySelectorAll('[role=alert]')].filter(visible).map(rect),
      scrollers: [...document.querySelectorAll('[data-scroll-container]')]
        .filter(visible)
        .map((n) => ({ ...rect(n), scrollHeight: n.scrollHeight, clientHeight: n.clientHeight })),
      controls: [...document.querySelectorAll('button,a,input,select,textarea')]
        .filter(visible)
        .map(rect)
        .filter((r) => r.y >= 0 && r.y < innerHeight && r.x >= 0 && r.x < innerWidth),
    }
  })
}
async function capture(p, role, c, size, theme, browserName, suffix = '') {
  const name = `${run}-${c.id}-${role}-${c.name}-${size.width}x${size.height}-${theme}-${browserName}${suffix}`
  const file = `${name}.png`
  const geometry = await metrics(p)
  const row = {
    caseId: c.id,
    name: c.name,
    role,
    route: new URL(p.url()).pathname + new URL(p.url()).search,
    viewport: size,
    theme,
    browser: browserName,
    state: suffix || 'opened',
    dataMode: c.dataMode || 'isolated-api',
    file,
    result: geometry.overflow > 1 ? 'FAIL' : 'PASS',
    metrics: geometry,
    reviewedBy: null,
    visualVerdict: 'PENDING',
    notes: [],
  }
  await p.screenshot({ path: resolve(output, file) })
  index.push(row)
  await persist()
  console.log(row.result + ' ' + file)
  return row
}
async function persist() {
  await writeFile(resolve(output, `${run}-index.json`), JSON.stringify(index, null, 2))
  await writeFile(resolve(output, `${run}-flows.json`), JSON.stringify(flows, null, 2))
  await writeFile(resolve(output, `${run}-errors.json`), JSON.stringify(errors, null, 2))
}
async function visit(p, role, c, size, theme, browserName) {
  await p.setViewportSize(size)
  await p.evaluate((t) => localStorage.setItem('paa.company.theme', t), theme)
  try {
    await p.goto(state.origin + c.route)
    await ready(p)
    if (c.action) await c.action(p)
    await p.waitForTimeout(100)
    await capture(p, role, c, size, theme, browserName)
    if (c.long && size.width === 390 && theme === 'light' && browserName === 'chromium') {
      await p
        .locator('[data-scroll-container]')
        .evaluateAll((nodes) => nodes.forEach((n) => (n.scrollTop = n.scrollHeight)))
      await p.waitForTimeout(60)
      await capture(p, role, c, size, theme, browserName, '-end')
    }
  } catch (e) {
    const row = await capture(p, role, c, size, theme, browserName, '-blocked').catch(() => null)
    if (row) {
      row.result = 'BLOCKED'
      row.error = e.message
      await persist()
    }
  }
}
async function baseline() {
  const browser = await chromium.launch()
  try {
    for (const role of ['employee', 'admin']) {
      const { context, p } = await login(browser, role)
      let cases = [...common(role), ...(role === 'admin' ? administrators : employees)].filter(
        (c) => c.id !== 'M18',
      )
      if (process.env.BUSINESS_FILTER)
        cases = cases.filter((c) => process.env.BUSINESS_FILTER.split(',').includes(c.name))
      for (const c of cases)
        for (const theme of ['light', 'dark']) {
          const prior =
            run !== 'baseline'
              ? [
                  ...JSON.parse(await readFile(resolve(output, 'baseline-index.json'), 'utf8')),
                  ...JSON.parse(
                    await readFile(resolve(output, 'baseline-recovery-index.json'), 'utf8'),
                  ),
                ]
              : []
          if (
            prior.some(
              (x) =>
                x.role === role && x.name === c.name && x.theme === theme && x.result === 'PASS',
            )
          )
            continue
          await visit(p, role, c, { width: 390, height: 844 }, theme, 'chromium')
        }
      await context.close()
    }
  } finally {
    await browser.close()
  }
}
async function narrow() {
  const browser = await chromium.launch()
  try {
    for (const role of ['employee', 'admin']) {
      const { context, p } = await login(browser, role)
      const cases = [...common(role), ...(role === 'admin' ? administrators : employees)].filter(
        (c) =>
          c.id !== 'M18' &&
          !c.modal &&
          !c.name.startsWith('missing') &&
          !c.name.includes('legacy') &&
          !c.name.includes('unknown') &&
          !c.name.includes('denied'),
      )
      for (const c of cases)
        await visit(p, role, c, { width: 320, height: 568 }, 'light', 'chromium')
      for (const c of cases.filter((c) =>
        [
          'work',
          'work-detail',
          'account',
          'rules',
          'reports-todo',
          'report-draft',
          'team-work',
          'team-weekly',
          'members',
          'models',
          'models-routing',
          'usage',
          'feedback-submit',
          'login-setup',
          'notifications-announcements',
        ].includes(c.name),
      ))
        await visit(p, role, c, { width: 360, height: 800 }, 'light', 'chromium')
      await context.close()
    }
  } finally {
    await browser.close()
  }
}
async function compatibility() {
  for (const [browserName, driver] of [
    ['chromium', chromium],
    ['webkit', webkit],
  ]) {
    const browser = await driver.launch()
    try {
      for (const role of ['employee', 'admin']) {
        const { context, p } = await login(browser, role)
        const cases = [...common(role), ...(role === 'admin' ? administrators : employees)].filter(
          (c) =>
            c.id !== 'M18' &&
            [
              'main-navigation',
              'settings-navigation',
              'command-search',
              'work-create',
              'work-detail',
              'report-edit',
              'report-submit',
              'report-draft',
              'account',
              'members',
              'member-create',
              'models',
              'models-routing',
              'team-work',
              'team-weekly',
              'login-setup',
            ].includes(c.name),
        )
        for (const c of cases)
          for (const size of browserName === 'webkit'
            ? [{ width: 390, height: 844 }]
            : [
                { width: 430, height: 932 },
                { width: 390, height: 480 },
                { width: 844, height: 390 },
              ])
            await visit(p, role, c, size, 'light', browserName)
        await context.close()
      }
    } finally {
      await browser.close()
    }
  }
}
async function journeys() {
  const browser = await chromium.launch()
  const size = { width: 390, height: 844 }
  async function step(p, role, id, name, source = 'isolated-api') {
    await capture(
      p,
      role,
      item(id, name, '', null, { dataMode: source }),
      size,
      (await p.locator('html').getAttribute('data-theme')) || 'light',
      'chromium',
    )
  }
  async function flow(id, action, p, role) {
    if (
      run === 'journeys-recovery' &&
      JSON.parse(await readFile(resolve(output, 'journeys-flows.json'), 'utf8')).some(
        (x) => x.id === id && x.result === 'PASS',
      )
    )
      return
    try {
      await action()
      flows.push({ id, result: 'PASS' })
    } catch (e) {
      flows.push({ id, result: 'FAIL', error: e.message })
      await step(p, role, id, 'flow-failure')
    }
    await persist()
  }
  try {
    const employee = await login(browser, 'employee')
    const admin = await login(browser, 'admin')
    const p = employee.p,
      a = admin.p
    await flow(
      'J01',
      async () => {
        await p.goto(state.origin + '/work')
        await ready(p)
        await button('展开导航')(p)
        await step(p, 'employee', 'J01', 'main-navigation-notifications-discovery')
        await button('系统设置')(p)
        await step(p, 'employee', 'J01', 'settings-navigation')
        await p.getByRole('link', { name: '账户', exact: true }).click()
        await expect(p.getByRole('heading', { name: '账户', exact: true })).toBeVisible()
        await button('展开导航')(p)
        await button('返回主菜单')(p)
        await p.getByRole('link', { name: '聊天搭子', exact: true }).click()
        await expect(p.getByRole('textbox', { name: '工作消息' })).toBeVisible()
        await p.reload()
        await expect(p.getByRole('textbox', { name: '工作消息' })).toBeVisible()
        await p.goto(state.origin + '/work')
        await button('展开导航')(p)
        await button('查找页面与操作')(p)
        await step(p, 'employee', 'J01', 'command-search')
        await p.getByRole('combobox', { name: '查找页面与操作' }).fill('通知')
        await step(p, 'employee', 'J01', 'search-notifications')
        await p.getByRole('option').filter({ hasText: '通知' }).click()
        await expect(p).toHaveURL(/notifications/)
        await step(p, 'employee', 'J01', 'notifications-via-command')
      },
      p,
      'employee',
    )
    await flow(
      'J09',
      async () => {
        await a.goto(state.origin + '/team')
        await ready(a)
        await button('周报')(a)
        await button('选择汇报周期')(a)
        await step(a, 'admin', 'J09', 'weekly-calendar')
        await button('关闭日期选择')(a)
        await a.getByLabel('搜索团队内容').fill('完全没有匹配的验收关键词')
        await a.getByLabel('搜索团队内容').press('Enter')
        await ready(a)
        await step(a, 'admin', 'J09', 'combined-filter-empty')
        await a.getByLabel('搜索团队内容').fill('')
        await a.getByLabel('搜索团队内容').press('Enter')
        await button('工作进展')(a)
        await button('筛选')(a)
        await a.getByRole('combobox', { name: '选择员工' }).selectOption(state.users.employee.id)
        await ready(a)
        await step(a, 'admin', 'J09', 'employee-work-filter')
        await a
          .getByRole('button', { name: /界面验收长标题/ })
          .first()
          .click()
        await step(a, 'admin', 'J09', 'embedded-work-open')
        await a.keyboard.press('Escape')
      },
      a,
      'admin',
    )
    await flow(
      'J12-feedback',
      async () => {
        const text =
          'Spec073合成反馈：手机端长内容布局核对。' + '附件卡片与操作说明需要完整可读。'.repeat(12)
        await p.goto(state.origin + '/settings/support')
        await p.getByLabel('问题描述').fill(text)
        await step(p, 'employee', 'J12', 'feedback-compose-long')
        await button('提交反馈')(p)
        await expect(p.getByRole('tab', { name: '反馈记录' })).toHaveAttribute(
          'aria-selected',
          'true',
        )
        await p
          .getByRole('button', { name: new RegExp('Spec073合成反馈') })
          .first()
          .click()
        await step(p, 'employee', 'J12', 'feedback-detail-employee')
        await p.keyboard.press('Escape')
        await p.reload()
        await expect(
          p.getByRole('button', { name: new RegExp('Spec073合成反馈') }).first(),
        ).toBeVisible()
        await a.goto(state.origin + '/settings/support?tab=records')
        await a
          .getByRole('button', { name: new RegExp('Spec073合成反馈') })
          .first()
          .click()
        const d = a.getByRole('dialog', { name: '反馈详情' })
        await d.getByRole('combobox', { name: '状态', exact: true }).selectOption('resolved')
        await d.getByLabel('处理说明').fill('仅为合成测试，已完成记录核对。')
        await step(a, 'admin', 'J12', 'feedback-detail-admin')
        await d.getByRole('button', { name: '保存处理结果' }).click()
        await expect(a.getByText('处理结果已保存')).toBeVisible()
        await a.keyboard.press('Escape')
        await p.reload()
        await p
          .getByRole('button', { name: new RegExp('Spec073合成反馈') })
          .first()
          .click()
        await expect(p.getByRole('dialog')).toContainText('仅为合成测试，已完成记录核对。')
        await step(p, 'employee', 'J12', 'feedback-resolved')
      },
      p,
      'employee',
    )
    await flow(
      'J12-member',
      async () => {
        await a.goto(state.origin + '/members')
        await ready(a)
        await button('添加成员')(a)
        let d = a.getByRole('dialog', { name: '添加成员' })
        await d.getByRole('button', { name: '保存', exact: true }).click()
        await expect(d.getByText('请输入姓名')).toBeVisible()
        await step(a, 'admin', 'J12', 'member-validation')
        const username = 'spec073_business_' + Date.now()
        await d.getByLabel('姓名').fill('手机验收特别长姓名用于验证换行和省略是否影响操作按钮位置')
        await d.getByLabel('账号').fill(username)
        await d.getByLabel('密码').fill('synthetic-business-1234')
        await d.getByRole('button', { name: '保存', exact: true }).click()
        await expect(d).toHaveCount(0)
        await a.getByRole('textbox', { name: '搜索成员' }).fill(username)
        await a.getByRole('textbox', { name: '搜索成员' }).press('Enter')
        await ready(a)
        await step(a, 'admin', 'J12', 'member-long-name')
        await button('更多操作')(a)
        await a.getByRole('menuitem', { name: '编辑姓名' }).click()
        d = a.getByRole('dialog', { name: '编辑姓名' })
        await d.getByLabel('姓名').fill('合成成员已修改')
        await step(a, 'admin', 'J12', 'member-edit')
        await d.getByRole('button', { name: '保存', exact: true }).click()
        await expect(d).toHaveCount(0)
        await a.reload()
        await expect(a.getByText('合成成员已修改')).toBeVisible()
        await button('更多操作')(a)
        await a.getByRole('menuitem', { name: '重置密码' }).click()
        await step(a, 'admin', 'J12', 'member-reset')
        await a.keyboard.press('Escape')
        await button('更多操作')(a)
        await a.getByRole('menuitem', { name: '删除账号' }).click()
        await step(a, 'admin', 'J12', 'member-delete')
        await a.getByRole('dialog').getByRole('button', { name: '删除账号', exact: true }).click()
        await expect(a.getByRole('heading', { name: '没有匹配的成员' })).toBeVisible()
        await step(a, 'admin', 'J12', 'member-delete-empty')
      },
      a,
      'admin',
    )
    await flow(
      'J12-memory',
      async () => {
        await p.goto(state.origin + '/settings/memory')
        await button('编辑')(p)
        await p
          .getByRole('textbox', { name: '记忆 Markdown' })
          .fill('# 合成记忆\n\n' + '喜欢简明且有依据的中文回复。'.repeat(18))
        await button('预览')(p)
        await step(p, 'employee', 'J12', 'memory-preview')
        await button('继续编辑')(p)
        await button('保存')(p)
        await expect(p.getByRole('heading', { name: '合成记忆' })).toBeVisible()
        await p.reload()
        await expect(p.getByRole('heading', { name: '合成记忆' })).toBeVisible()
        await step(p, 'employee', 'J12', 'memory-persisted')
        await button('编辑')(p)
        await p.getByRole('textbox', { name: '记忆 Markdown' }).fill('取消的内容')
        await button('取消')(p)
        await expect(p.getByText('取消的内容')).toHaveCount(0)
      },
      p,
      'employee',
    )
    await flow(
      'J11-account-rules',
      async () => {
        await a.goto(state.origin + '/settings/account')
        await tab('修改密码')(a)
        await button('保存密码并重新登录')(a)
        await step(a, 'admin', 'J11', 'password-validation')
        await a.goto(state.origin + '/settings/rules')
        await tab('周报')(a)
        await step(a, 'admin', 'J11', 'rules-weekly')
        await button('保存汇报规则')(a)
        await expect(a.getByText('汇报规则已保存，从后续安排生效')).toBeVisible()
        await a.reload()
        await step(a, 'admin', 'J11', 'rules-saved-reload')
        await a.goto(state.origin + '/settings/login')
        await button('保存配置')(a)
        await expect(a.getByLabel('企业 CorpId')).toHaveAttribute('aria-invalid', 'true')
        await step(a, 'admin', 'J11', 'login-configuration-validation')
      },
      a,
      'admin',
    )
    await flow(
      'S06-members-network',
      async () => {
        await a.route('**/api/v1/members', (r) => r.abort('failed'))
        await a.goto(state.origin + '/members')
        await expect(a.getByRole('button', { name: '重试', exact: true })).toBeVisible()
        await step(a, 'admin', 'S06', 'members-error', 'controlled-ui')
        await a.unroute('**/api/v1/members')
        await button('重试')(a)
        await expect(a.getByRole('table', { name: '成员列表' })).toBeVisible()
        await step(a, 'admin', 'S06', 'members-recovered')
      },
      a,
      'admin',
    )
    await flow(
      'S01-members-empty-paged',
      async () => {
        await a.route('**/api/v1/members', (r) => r.fulfill({ json: { items: [] } }))
        await a.goto(state.origin + '/members')
        await expect(a.getByRole('button', { name: '添加第一位成员' })).toBeVisible()
        await step(a, 'admin', 'S01', 'members-empty', 'controlled-ui')
        await a.unroute('**/api/v1/members')
        await a.route('**/api/v1/members', async (r) => {
          const response = await r.fetch()
          const original = await response.json()
          const member = original.items.find((x) => x.role === 'employee')
          await r.fulfill({
            json: {
              items: Array.from({ length: 23 }, (_, n) => ({
                ...member,
                id: `controlled-${n}`,
                name: `合成长姓名成员 ${n + 1} ` + '项目协作'.repeat(6),
                username: `controlled_${n}`,
              })),
            },
          })
        })
        await a.reload()
        await button('下一页')(a)
        await step(a, 'admin', 'S01', 'members-page2', 'controlled-ui')
        await a.unroute('**/api/v1/members')
      },
      a,
      'admin',
    )
    await flow(
      'S08-pet',
      async () => {
        await p.goto(state.origin + '/work')
        await p.evaluate(() => localStorage.setItem('paa.company.pet-visible', 'true'))
        await p.reload()
        await ready(p)
        await step(p, 'employee', 'S08', 'pet-enabled-work')
        await p.getByRole('button', { name: /^Noria(?:，|$)/ }).click()
        await step(p, 'employee', 'S08', 'pet-modal')
        await p.getByRole('button', { name: '深色', exact: true }).click()
        await step(p, 'employee', 'S08', 'pet-modal-dark')
        await p.keyboard.press('Escape')
        await p.goto(state.origin + `/reports/${ids.employee.weekly}`)
        await ready(p)
        await step(p, 'employee', 'S08', 'pet-enabled-report')
        await p.evaluate(() => localStorage.setItem('paa.company.pet-visible', 'false'))
        await p.reload()
      },
      p,
      'employee',
    )
    await employee.context.close()
    await admin.context.close()
    const ctx = await browser.newContext({
      viewport: size,
      isMobile: true,
      hasTouch: true,
      locale: 'zh-CN',
    })
    const n = await ctx.newPage()
    n.setDefaultTimeout(5000)
    await flow(
      'M01-anonymous',
      async () => {
        await n.goto(state.origin)
        await ready(n)
        await step(n, 'anonymous', 'M01', 'login-entry')
        await button('直接登录')(n)
        await step(n, 'anonymous', 'M01', 'login-form')
        await button('登录')(n)
        await step(n, 'anonymous', 'M01', 'login-validation')
        await n.getByLabel('账号', { exact: true }).fill('nonexistent_spec073')
        await n.getByLabel('密码', { exact: true }).fill('incorrect')
        await button('登录')(n)
        await expect(n.getByRole('alert')).toBeVisible()
        await step(n, 'anonymous', 'M01', 'login-error')
        await n.goto(state.origin + '/desktop/connect?request=invalid')
        await ready(n)
        await step(n, 'anonymous', 'M01', 'desktop-anonymous')
        await n.goto(state.origin + '/?dingtalk=failed')
        await ready(n)
        await step(n, 'anonymous', 'M01', 'dingtalk-failure')
      },
      n,
      'anonymous',
    )
    await ctx.close()
  } finally {
    await browser.close()
    await persist()
  }
}
async function extras() {
  const browser = await chromium.launch()
  const size = { width: 390, height: 844 }
  async function snap(p, role, id, name, dataMode = 'isolated-api') {
    await capture(
      p,
      role,
      item(id, name, '', null, { dataMode }),
      p.viewportSize(),
      (await p.locator('html').getAttribute('data-theme')) || 'light',
      'chromium',
    )
  }
  async function flow(id, action, p, role) {
    if (
      run === 'extras-recovery' &&
      JSON.parse(await readFile(resolve(output, 'extras-flows.json'), 'utf8')).some(
        (x) => x.id === id && x.result === 'PASS',
      )
    )
      return
    try {
      await action()
      flows.push({ id, result: 'PASS' })
    } catch (e) {
      flows.push({ id, result: 'FAIL', error: e.message })
      await snap(p, role, id, 'failure')
    }
    await persist()
  }
  try {
    const { context, p } = await login(browser, 'employee')
    const ownAdmin = await login(browser, 'admin')
    const a = ownAdmin.p
    await flow(
      'M15-M16-employee-expanded',
      async () => {
        for (const [name, path, label] of [
          ['account-password', '/settings/account', '修改密码'],
          ['account-dingtalk', '/settings/account', '钉钉账号关联'],
          ['rules-weekly', '/settings/rules', '周报'],
        ]) {
          for (const [width, height, theme] of [
            [390, 844, 'light'],
            [390, 844, 'dark'],
            [320, 568, 'light'],
          ]) {
            await p.setViewportSize({ width, height })
            await p.evaluate((t) => localStorage.setItem('paa.company.theme', t), theme)
            await p.goto(state.origin + path)
            await ready(p)
            await p.locator('summary').filter({ hasText: label }).click()
            await snap(p, 'employee', path.includes('account') ? 'M15' : 'M16', name)
            await p
              .locator('[data-scroll-container]')
              .evaluateAll((ns) => ns.forEach((n) => (n.scrollTop = n.scrollHeight)))
            await snap(p, 'employee', path.includes('account') ? 'M15' : 'M16', name + '-end')
          }
        }
      },
      p,
      'employee',
    )
    await flow(
      'M10-narrow-selector-recovery',
      async () => {
        for (const name of ['reports-weekly', 'reports-schedule'])
          await visit(
            p,
            'employee',
            employees.find((c) => c.name === name),
            { width: 320, height: 568 },
            'light',
            'chromium',
          )
      },
      p,
      'employee',
    )
    await flow(
      'S04-team-calendar-range',
      async () => {
        await a.goto(state.origin + '/team?view=reports&kind=weekly')
        await ready(a)
        await button('选择汇报周期')(a)
        await a.locator('summary').filter({ hasText: '更多日期筛选' }).click()
        await a.getByLabel('开始日期').fill('2027-01-01')
        await a.getByLabel('结束日期').fill('2026-01-01')
        await snap(a, 'admin', 'S04', 'calendar-range-validation')
        await expect(a.getByRole('button', { name: '应用范围' })).toBeDisabled()
        await a.getByLabel('结束日期').fill('2027-01-21')
        await button('应用范围')(a)
        await expect(a.getByRole('dialog', { name: '选择汇报周期' })).toHaveCount(0)
        await snap(a, 'admin', 'S04', 'calendar-custom-empty')
      },
      a,
      'admin',
    )
    await flow(
      'M09-work-materials',
      async () => {
        await p.setViewportSize(size)
        if (!ids.businessWork) {
          await p.goto(state.origin + '/work')
          await button('新建工作')(p)
          const d = p.getByRole('dialog')
          await d.getByRole('textbox', { name: '工作事项' }).fill('Spec073手机材料布局专用工作')
          await d.getByRole('button', { name: '创建工作', exact: true }).click()
          await expect(d).toHaveCount(0)
          ids.businessWork = new URL(p.url()).pathname.split('/').at(-1)
          await writeFile(
            supplemental,
            JSON.stringify(
              { announcement: ids.announcement, businessWork: ids.businessWork },
              null,
              2,
            ),
          )
          await button('编辑内容')(p)
          await p.getByRole('textbox', { name: '工作正文' }).fill('仅用于手机材料布局与移除检查。')
          await p.getByLabel('正文材料').setInputFiles(
            Array.from({ length: 5 }, (_, i) => ({
              name: `验收材料-${i + 1}-${'很长文件名'.repeat(i + 1)}.txt`,
              mimeType: 'text/plain',
              buffer: Buffer.from('手机布局合成材料'),
            })),
          )
          await expect(p.getByRole('button', { name: '保存内容' })).toBeEnabled()
          await button('保存内容')(p)
          await expect(p.getByRole('button', { name: '编辑内容' })).toBeVisible()
        }
        await p.goto(state.origin + '/work/' + ids.businessWork)
        await ready(p)
        await button('管理工作')(p)
        await p.getByRole('menuitem', { name: /全部附件/ }).click()
        await snap(p, 'employee', 'M09', 'all-materials-modal')
        await p
          .getByRole('button', { name: /验收材料-1-/ })
          .first()
          .click()
        await snap(p, 'employee', 'M09', 'material-detail-modal')
        await p.keyboard.press('Escape')
        await p.keyboard.press('Escape')
        await button('编辑内容')(p)
        await p
          .getByRole('button', { name: /从内容移除/ })
          .first()
          .click()
        await button('保存内容')(p)
        await expect(p.getByRole('button', { name: '编辑内容' })).toBeVisible()
        await button('管理工作')(p)
        await p.getByRole('menuitem', { name: /全部附件/ }).click()
        await p.getByRole('button', { name: '移除材料', exact: true }).first().click()
        await snap(p, 'employee', 'M09', 'remove-material-modal')
        await p.keyboard.press('Escape')
        await p.keyboard.press('Escape')
      },
      p,
      'employee',
    )
    await flow(
      'M19-usage-horizontal',
      async () => {
        await a.goto(state.origin + '/settings/usage')
        await ready(a)
        const region = a.getByRole('region', { name: '模型调用记录' })
        await region.scrollIntoViewIfNeeded()
        await region.evaluate((n) => (n.scrollLeft = n.scrollWidth))
        await snap(a, 'admin', 'M19', 'usage-scroll-right')
        await expect(region).toBeVisible()
      },
      a,
      'admin',
    )
    await flow(
      'M01-expired-session',
      async () => {
        await p.route('**/api/v1/auth/me', (r) =>
          r.fulfill({ status: 401, json: { detail: 'session expired' } }),
        )
        await p.goto(state.origin + '/work')
        await ready(p)
        await snap(p, 'employee', 'M01', 'session-expired', 'controlled-ui')
        await p.unroute('**/api/v1/auth/me')
      },
      p,
      'employee',
    )
    await context.close()
    await ownAdmin.context.close()
    const peer = await login(browser, 'peer')
    await flow(
      'M07-material-source',
      async () => {
        const messages = await api(
          peer.p,
          '/api/v1/messages?conversationId=0ae368a3-8383-4ef6-968f-c356d50c52f2',
        )
        const m = messages.items.find((x) => x.attachments?.length) || messages.items[0]
        await writeFile(resolve(output, 'peer-message-shape.json'), JSON.stringify(m, null, 2))
        await peer.p.goto(state.origin + '/messages/' + m.id)
        await ready(peer.p)
        await snap(peer.p, 'peer', 'M07', 'source-mixed-materials')
        await peer.p
          .locator('[data-scroll-container]')
          .evaluateAll((ns) => ns.forEach((n) => (n.scrollTop = n.scrollHeight)))
        await snap(peer.p, 'peer', 'M07', 'source-mixed-materials-end')
        const preview = peer.p.getByRole('button', { name: /预览/ })
        if (await preview.count()) {
          await preview.first().click()
          await snap(peer.p, 'peer', 'M07', 'source-image-preview')
        }
      },
      peer.p,
      'peer',
    )
    await peer.context.close()
  } finally {
    await browser.close()
    await persist()
  }
}

async function finalChecks() {
  const size = { width: 390, height: 844 }
  const browser = await chromium.launch()
  try {
    const { context, p } = await login(browser, 'employee')
    const admin = await login(browser, 'admin')
    if (!run.endsWith('recovery')) {
      await p.goto(state.origin + '/work')
      await ready(p)
      await button('展开导航')(p)
      await button('查找页面与操作')(p)
      await p.getByRole('combobox', { name: '查找页面与操作' }).fill('通知')
      await p.getByRole('option').filter({ hasText: '通知' }).click()
      await expect(p.getByRole('heading', { name: '通知', exact: true })).toBeVisible()
      await ready(p)
      await capture(
        p,
        'employee',
        item('J01', 'notification-route-settled', ''),
        size,
        'light',
        'chromium',
      )
    }
    await admin.p.goto(state.origin + '/team')
    await ready(admin.p)
    await admin.p
      .getByRole('button', { name: /界面验收长标题/ })
      .first()
      .click()
    await expect(admin.p.getByRole('dialog', { name: '工作详情', exact: true })).toBeVisible()
    await ready(admin.p)
    await capture(
      admin.p,
      'admin',
      item('J09', 'embedded-work-settled', ''),
      size,
      'light',
      'chromium',
    )
    await admin.p.goto(state.origin + '/settings/rules')
    await expect(admin.p.getByRole('button', { name: '保存汇报规则' })).toBeVisible()
    await ready(admin.p)
    await capture(
      admin.p,
      'admin',
      item('J11', 'rules-reload-settled', ''),
      size,
      'light',
      'chromium',
    )
    await context.close()
    await admin.context.close()
    flows.push({ id: 'final-stable-captures', result: 'PASS' })
  } catch (e) {
    flows.push({ id: 'final-stable-captures', result: 'FAIL', error: e.message })
  } finally {
    await browser.close()
    await persist()
  }
  const wk = await webkit.launch()
  try {
    const { context, p } = await login(wk, 'employee')
    await p.goto(state.origin + '/work')
    await button('新建工作')(p)
    const d = p.getByRole('dialog')
    await d.getByRole('textbox', { name: '工作事项' }).fill('Spec073 WebKit完整工作流程')
    await d.getByRole('button', { name: '创建工作', exact: true }).click()
    await expect(d).toHaveCount(0)
    await button('编辑内容')(p)
    await p.getByRole('textbox', { name: '工作正文' }).fill('WebKit保存后刷新仍可见的合成内容。')
    await button('保存内容')(p)
    await expect(p.getByRole('button', { name: '编辑内容' })).toBeVisible()
    await p.reload()
    await expect(
      p.getByText('WebKit保存后刷新仍可见的合成内容。', { exact: true }).first(),
    ).toBeVisible()
    await ready(p)
    await capture(p, 'employee', item('J07', 'webkit-work-persisted', ''), size, 'light', 'webkit')
    await button('管理工作')(p)
    await p.getByRole('menuitem', { name: '删除工作' }).click()
    await p.getByRole('dialog').getByRole('button', { name: '确认删除', exact: true }).click()
    await expect(p).toHaveURL(/\/work$/)
    flows.push({ id: 'J07-webkit', result: 'PASS' })
    await p.goto(state.origin + '/reports/' + ids.employee.workflow)
    await button('编辑草稿')(p)
    await p.getByRole('textbox').first().fill('WebKit汇报编辑、保存及提交验收。')
    await button('保存草稿')(p)
    await expect(p.getByRole('button', { name: '编辑草稿' })).toBeVisible()
    await p.reload()
    await expect(
      p.getByText('WebKit汇报编辑、保存及提交验收。', { exact: true }).first(),
    ).toBeVisible()
    await button('提交报告')(p)
    await p.getByRole('dialog').getByRole('button', { name: '确认提交' }).click()
    await expect(p.getByText('报告已提交', { exact: true })).toBeVisible()
    await p.reload()
    await ready(p)
    await expect(
      p.getByText('WebKit汇报编辑、保存及提交验收。', { exact: true }).first(),
    ).toBeVisible()
    await capture(
      p,
      'employee',
      item('J08', 'webkit-report-submitted', ''),
      size,
      'light',
      'webkit',
    )
    flows.push({ id: 'J08-webkit', result: 'PASS' })
    await context.close()
  } catch (e) {
    flows.push({ id: 'webkit-write-flow', result: 'FAIL', error: e.message })
  } finally {
    await wk.close()
    await persist()
  }
}

async function webkitFinish() {
  const b = await webkit.launch()
  try {
    const { context, p } = await login(b, 'employee')
    const works = await api(p, '/api/v1/work-items')
    const w = works.items.find((x) => x.title === 'Spec073 WebKit完整工作流程')
    if (w && !run.includes('report')) {
      await p.goto(state.origin + '/work/' + w.id)
      await button('管理工作')(p)
      await p.getByRole('menuitem', { name: '删除工作' }).click()
      await p.getByRole('dialog').getByRole('button', { name: '确认删除' }).click()
      await expect(p).toHaveURL(/\/work$/)
      flows.push({ id: 'J07-webkit-delete-completion', result: 'PASS' })
    }
    await p.goto(state.origin + '/reports/' + ids.employee.workflow)
    await button('编辑草稿')(p)
    await p.getByRole('textbox').first().fill('WebKit汇报编辑、保存及提交验收。')
    await button('保存草稿')(p)
    await expect(p.getByRole('button', { name: '编辑草稿' })).toBeVisible()
    await p.reload()
    await expect(
      p.getByText('WebKit汇报编辑、保存及提交验收。', { exact: true }).first(),
    ).toBeVisible()
    await button('提交报告')(p)
    await p.getByRole('dialog').getByRole('button', { name: '确认提交' }).click()
    await expect(p.getByText('报告已提交', { exact: true })).toBeVisible()
    await p.reload()
    await ready(p)
    await expect(p.getByRole('button', { name: '提交报告', exact: true })).toBeDisabled()
    await capture(
      p,
      'employee',
      item('J08', 'webkit-report-submitted', ''),
      { width: 390, height: 844 },
      'light',
      'webkit',
    )
    flows.push({ id: 'J08-webkit', result: 'PASS' })
    await context.close()
  } catch (e) {
    flows.push({ id: 'webkit-completion', result: 'FAIL', error: e.message })
  } finally {
    await b.close()
    await persist()
  }
}
async function gaps() {
  const browser = await chromium.launch()
  const size = { width: 390, height: 844 }
  async function shot(p, role, id, name, dataMode = 'isolated-api') {
    await ready(p)
    await capture(
      p,
      role,
      item(id, name, '', null, { dataMode }),
      p.viewportSize(),
      (await p.locator('html').getAttribute('data-theme')) || 'light',
      'chromium',
    )
  }
  async function flow(id, p, role, action) {
    if (
      run === 'gaps-recovery' &&
      JSON.parse(await readFile(resolve(output, 'gaps-flows.json'), 'utf8')).some(
        (x) => x.id === id && x.result === 'PASS',
      )
    )
      return
    try {
      await action()
      flows.push({ id, result: 'PASS' })
    } catch (e) {
      flows.push({ id, result: 'FAIL', error: e.message })
      await shot(p, role, id, 'gap-failure')
    }
    await persist()
  }
  try {
    const admin = await login(browser, 'admin'),
      employee = await login(browser, 'employee')
    const a = admin.p,
      p = employee.p
    await flow('M20-clear-memory', p, 'employee', async () => {
      await p.goto(state.origin + '/settings/memory')
      await expect(p.getByRole('button', { name: '清空记忆' })).toBeVisible()
      await shot(p, 'employee', 'M20', 'before-clear')
      p.removeAllListeners('dialog')
      let accept = false
      let seen = []
      p.on('dialog', async (dialog) => {
        seen.push({ type: dialog.type(), message: dialog.message(), accepted: accept })
        if (accept) await dialog.accept()
        else await dialog.dismiss()
      })
      await button('清空记忆')(p)
      await expect(p.getByRole('button', { name: '清空记忆' })).toBeVisible()
      accept = true
      await button('清空记忆')(p)
      await expect(p.getByText('还没有记忆。', { exact: false })).toBeVisible()
      await p.reload()
      await expect(p.getByText('还没有记忆。', { exact: false })).toBeVisible()
      await shot(p, 'employee', 'M20', 'clear-persisted')
      await writeFile(resolve(output, 'memory-confirm-dialogs.json'), JSON.stringify(seen, null, 2))
      expect(seen.map((x) => x.accepted)).toEqual([false, true])
    })
    await flow('M21-existing-voiceprints', a, 'admin', async () => {
      let rows = [
        {
          memberId: 'controlled-ready',
          name: '合成很长姓名声纹成员用于手机端换行检查',
          role: 'employee',
          active: true,
          state: 'ready',
          revision: 2,
          ready: true,
          filename: '合成声音.wav',
          error: '',
          speechSeconds: 36,
          updatedAt: new Date().toISOString(),
        },
        {
          memberId: 'controlled-failed',
          name: '合成登记失败成员',
          role: 'employee',
          active: true,
          state: 'failed',
          revision: 1,
          ready: false,
          filename: '合成错误.wav',
          error: '录音中没有足够清晰的单人声音，请重新上传。',
          speechSeconds: 0,
          updatedAt: new Date().toISOString(),
        },
      ]
      const requests = []
      await a.route('**/api/v1/settings/voiceprints', (r) =>
        r.fulfill({ json: { modelId: 'synthetic-model', items: rows, limit: 20 } }),
      )
      await a.route('**/api/v1/settings/voiceprints/controlled-*', async (r) => {
        requests.push({ url: new URL(r.request().url()).pathname, method: r.request().method() })
        if (r.request().method() === 'DELETE')
          rows = rows.filter((x) => !r.request().url().endsWith(x.memberId))
        await r.fulfill({ json: { ok: true } })
      })
      await a.goto(state.origin + '/settings/voiceprints')
      await expect(a.getByText('已就绪', { exact: true })).toBeVisible()
      await shot(a, 'admin', 'M21', 'ready-and-failed-rows', 'controlled-ui')
      expect(await a.locator('audio').count()).toBe(0)
      expect(await a.getByRole('button', { name: /播放/ }).count()).toBe(0)
      await button('替换录音')(a)
      await shot(a, 'admin', 'M21', 'replace-enrollment', 'controlled-ui')
      await a.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click()
      a.removeAllListeners('dialog')
      const seen = []
      a.on('dialog', async (d) => {
        seen.push({ type: d.type(), message: d.message() })
        await d.accept()
      })
      await a
        .getByRole('button', {
          name: '删除 合成很长姓名声纹成员用于手机端换行检查 的声纹',
          exact: true,
        })
        .click()
      await expect(
        a.getByText('合成很长姓名声纹成员用于手机端换行检查', { exact: true }),
      ).toHaveCount(0)
      await shot(a, 'admin', 'M21', 'deleted-ready-row', 'controlled-ui')
      await writeFile(
        resolve(output, 'voiceprint-controlled-evidence.json'),
        JSON.stringify(
          {
            requests,
            dialogs: seen,
            playback: 'No playback control or audio element exists in the current product UI.',
          },
          null,
          2,
        ),
      )
      expect(requests.some((x) => x.method === 'DELETE')).toBe(true)
      await a.unroute('**/api/v1/settings/voiceprints')
      await a.unroute('**/api/v1/settings/voiceprints/controlled-*')
    })
    await flow('M19-failed-usage', a, 'admin', async () => {
      await a.route('**/api/v1/settings/model-usage?*', async (r) => {
        const response = await r.fetch(),
          data = await response.json()
        data.items = [
          {
            id: 'controlled-failure',
            serviceId: null,
            service: '合成服务：很长模型名称与失败说明验证',
            model: 'synthetic-very-long-reasoning-model-version-mobile-check',
            purpose: 'assistant',
            state: 'failed',
            createdAt: new Date().toISOString(),
            startedAt: new Date().toISOString(),
            elapsedMs: 34000,
            inputTokens: 1234,
            outputTokens: null,
            errorCode: 'provider_failure',
            error: '模型服务暂时不可用，请稍后重试。该条记录用于手机布局检查。',
          },
        ]
        data.summary = {
          calls: 1,
          successRate: 0,
          states: { failed: 1 },
          averageMs: 34000,
          durationKnown: 1,
          inputTokens: 1234,
          outputTokens: 0,
          inputKnown: 1,
          outputKnown: 0,
        }
        data.nextCursor = null
        await r.fulfill({ json: data })
      })
      await a.goto(state.origin + '/settings/usage')
      await expect(a.getByText('失败', { exact: true })).toBeVisible()
      const region = a.getByRole('region', { name: '模型调用记录' })
      await region.scrollIntoViewIfNeeded()
      await shot(a, 'admin', 'M19', 'failed-usage-left', 'controlled-ui')
      await region.evaluate((n) => (n.scrollLeft = n.scrollWidth))
      await shot(a, 'admin', 'M19', 'failed-usage-right', 'controlled-ui')
      await a.unroute('**/api/v1/settings/model-usage?*')
    })
    await flow('M15-password-success', a, 'admin', async () => {
      const username = 'spec073_password_' + Date.now()
      const old = 'Spec073-old-password!',
        next = 'Spec073-new-password!'
      const member = await api(a, '/api/v1/members', 'POST', {
        name: '独立密码验收合成账号',
        username,
        password: old,
        role: 'employee',
      })
      state.users.password = { id: member.id, username, password: old }
      const own = await login(browser, 'password')
      const q = own.p
      await q.goto(state.origin + '/settings/account')
      await q.locator('summary').filter({ hasText: '修改密码' }).click()
      await q.getByLabel('当前密码', { exact: false }).fill(old)
      await q.locator('input[name="newPassword"]').fill(next)
      await q.getByLabel('确认新密码', { exact: false }).fill(next)
      await shot(q, 'password', 'M15', 'password-ready')
      await button('保存密码并重新登录')(q)
      await expect(q.getByRole('button', { name: '直接登录', exact: true })).toBeVisible()
      await shot(q, 'password', 'M15', 'password-logged-out')
      await button('直接登录')(q)
      await q.getByLabel('账号', { exact: true }).fill(username)
      await q.getByLabel('密码', { exact: true }).fill(next)
      await button('登录')(q)
      await expect(
        q.getByRole('navigation', { name: '工作空间', includeHidden: true }),
      ).toBeAttached()
      await q.goto(state.origin + '/settings/account')
      await expect(q.getByText('独立密码验收合成账号', { exact: true })).toBeVisible()
      await shot(q, 'password', 'M15', 'password-relogin-success')
      await own.context.close()
    })
    await employee.context.close()
    await admin.context.close()
    const peer = await login(browser, 'peer')
    await flow('M07-image-preview-loaded', peer.p, 'peer', async () => {
      const messages = await api(
        peer.p,
        '/api/v1/messages?conversationId=0ae368a3-8383-4ef6-968f-c356d50c52f2',
      )
      const m =
        messages.items.find((x) =>
          x.attachments?.some((y) => y.mimeType?.startsWith('image/') || y.name?.endsWith('.png')),
        ) || messages.items.find((x) => x.attachments?.length)
      await peer.p.goto(state.origin + '/messages/' + m.id)
      await peer.p.getByRole('button', { name: /预览/ }).first().click()
      const img = peer.p.getByRole('dialog').locator('img')
      await expect(img).toBeVisible()
      await expect.poll(() => img.evaluate((n) => n.complete && n.naturalWidth > 0)).toBe(true)
      await shot(peer.p, 'peer', 'M07', 'source-preview-loaded')
      await peer.p.keyboard.press('Escape')
      await expect(peer.p.getByRole('dialog')).toHaveCount(0)
    })
    await peer.context.close()
    const ctx = await browser.newContext({
      viewport: size,
      isMobile: true,
      hasTouch: true,
      locale: 'zh-CN',
    })
    const q = await ctx.newPage()
    await q.goto(state.origin)
    await flow('M01-auth-responsive', q, 'anonymous', async () => {
      for (const [width, height, theme] of [
        [320, 568, 'light'],
        [320, 568, 'dark'],
        [360, 800, 'light'],
        [360, 800, 'dark'],
        [390, 844, 'dark'],
      ]) {
        await q.setViewportSize({ width, height })
        await q.evaluate((v) => localStorage.setItem('paa.company.theme', v), theme)
        await q.goto(state.origin)
        await ready(q)
        await shot(q, 'anonymous', 'M01', 'entry-responsive')
        await button('直接登录')(q)
        await expect(q.getByLabel('账号', { exact: true })).toBeVisible()
        await shot(q, 'anonymous', 'M01', 'form-responsive')
      }
    })
    await ctx.close()
  } finally {
    await browser.close()
    await persist()
  }
}

async function acceptanceNavigation() {
  const browser = await chromium.launch()
  const animationEvidence = []
  const previous =
    run === 'acceptance-nav'
      ? []
      : JSON.parse(await readFile(resolve(output, 'acceptance-nav-index.json'), 'utf8'))
  async function shot(p, role, name, size, theme) {
    if (
      previous.some(
        (row) =>
          row.role === role &&
          row.name === name &&
          row.viewport.width === size.width &&
          row.theme === theme,
      )
    )
      return
    await capture(p, role, item('M02', name, '/work'), size, theme, 'chromium')
  }
  async function settled(p, selector, label) {
    const node = p.locator(selector)
    await expect(node).toBeVisible()
    const animations = await node.evaluate(async (element) => {
      const pending = element
        .getAnimations({ subtree: true })
        .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity)
      const timing = pending.map((animation) => ({
        name: animation.animationName || animation.constructor.name,
        duration: animation.effect?.getComputedTiming().duration,
      }))
      await Promise.all(pending.map((animation) => animation.finished.catch(() => {})))
      await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))
      return {
        timing,
        opacity: getComputedStyle(element).opacity,
        transform: getComputedStyle(element).transform,
      }
    })
    animationEvidence.push({ label, url: p.url(), ...animations })
  }
  try {
    for (const role of ['employee', 'admin']) {
      const { context, p } = await login(browser, role)
      for (const [width, height, theme] of [
        [390, 844, 'light'],
        [390, 844, 'dark'],
        [320, 568, 'light'],
        [360, 800, 'light'],
      ]) {
        const size = { width, height }
        await p.setViewportSize(size)
        await p.evaluate((value) => localStorage.setItem('paa.company.theme', value), theme)
        await p.goto(state.origin + '/work')
        await ready(p)
        await button('展开导航')(p)
        await settled(p, '#sidebar-navigation', `${role}-${width}-${theme}-main`)
        await shot(p, role, 'main-navigation-settled', size, theme)
        await button('系统设置')(p)
        await expect(p.getByRole('navigation', { name: '系统设置', exact: true })).toBeVisible()
        await settled(p, '#sidebar-navigation', `${role}-${width}-${theme}-settings`)
        await shot(p, role, 'settings-navigation-settled', size, theme)
        await button('返回主菜单')(p)
        await expect(p.getByRole('navigation', { name: '工作空间', exact: true })).toBeVisible()
        await button('查找页面与操作')(p)
        await expect(p.getByRole('combobox', { name: '查找页面与操作' })).toBeVisible()
        await settled(
          p,
          'dialog[open]:has([role="combobox"]), [role="dialog"]:has([role="combobox"])',
          `${role}-${width}-${theme}-search`,
        )
        await shot(p, role, 'command-search-settled', size, theme)
        await p.keyboard.press('Escape')
      }
      if (role === 'employee') {
        for (const size of [
          { width: 320, height: 568 },
          { width: 360, height: 800 },
        ]) {
          await p.setViewportSize(size)
          await p.evaluate(() => localStorage.setItem('paa.company.theme', 'light'))
          await p.goto(state.origin + '/work/missing-work')
          await ready(p)
          await expect(p.getByRole('alert')).toContainText('记录不存在或无权查看')
          await capture(
            p,
            role,
            item('M24', 'missing-work-narrow', '/work/missing-work'),
            size,
            'light',
            'chromium',
          )
          await p.goto(state.origin + '/members')
          await expect(p).toHaveURL(/\/assistant\//)
          await expect(p.getByRole('textbox', { name: '工作消息' })).toBeVisible()
          await ready(p)
          const row = await capture(
            p,
            role,
            item('M24', 'unauthorized-route-fallback-narrow', '/members'),
            size,
            'light',
            'chromium',
          )
          row.requestedRoute = '/members'
          row.sharedBasis =
            'Employee /members has no registered route; it uses AppRoutes wildcard Navigate /assistant, shared with unknown routes. This is UI fallback coverage, not API authorization verification.'
          await persist()
        }
      }
      await context.close()
    }
    flows.push({
      id: 'acceptance-navigation-and-errors',
      result: 'PASS',
      note: 'Animations ran naturally and their finished promises were awaited; no reduced motion or disabled animation override.',
    })
  } finally {
    await writeFile(
      resolve(output, `${run}-animation-evidence.json`),
      JSON.stringify(animationEvidence, null, 2),
    )
    await browser.close()
    await persist()
  }
}

if (run.startsWith('acceptance-nav')) await acceptanceNavigation()
else if (run.startsWith('gaps')) await gaps()
else if (run.startsWith('webkit-')) await webkitFinish()
else if (run.startsWith('final-checks')) await finalChecks()
else if (run.startsWith('extras')) await extras()
else if (run.startsWith('journeys')) await journeys()
else if (run.startsWith('baseline')) await baseline()
else if (run === 'narrow') await narrow()
else if (run === 'compatibility') await compatibility()
await persist()
