import { chromium, expect } from '@playwright/test'
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

// Run only against environment.py's disposable database and synthetic records.
// SPEC044_STATE=... UI_LAYOUT_RECORDS=... node scripts/company/web-acceptance/ui-layout.mjs
// UI_LAYOUT_FILTER=work-history,team-work-drawer reruns selected cases without losing other evidence.
// UI_LAYOUT_RESUME=1 skips captured role/case/viewport/theme entries and retries failures.
const output = resolve(process.env.UI_LAYOUT_OUTPUT || 'artifacts/spec050')
const statePath = process.env.SPEC044_STATE
if (!statePath) throw new Error('SPEC044_STATE must identify isolated acceptance credentials')
if ((await stat(statePath)).mode & 0o077) throw new Error('Credentials must have mode 0600')
const state = JSON.parse(await readFile(statePath, 'utf8'))
if (!/^spec044_web_[a-f0-9]{12}$/.test(state.schema)) throw new Error('Not an isolated schema')
if (state.origin !== 'http://127.0.0.1:5196') throw new Error('Only the isolated UI is allowed')
const ids = JSON.parse(
  await readFile(process.env.UI_LAYOUT_RECORDS || resolve(output, 'records.json'), 'utf8'),
)
const selected = process.env.UI_LAYOUT_FILTER?.split(',')
const resume = process.env.UI_LAYOUT_RESUME === '1'
await mkdir(resolve(output, 'screenshots'), { recursive: true })
let results = []
if (selected || resume) {
  try {
    results = JSON.parse(await readFile(resolve(output, 'manifest.json'), 'utf8'))
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
  }
}
const browser = await chromium.launch()
const sizes = { desktop: [1440, 1000], mobile: [390, 844] }
const failures = []
const routeCase = (name, path, ready, action, extra = {}) => ({
  name,
  path,
  ready,
  action,
  ...extra,
})
const textReady = (text) => (page) =>
  expect(page.getByRole('heading', { name: text, exact: true })).toBeVisible()
const assistantReady = (page) =>
  expect(page.getByRole('textbox', { name: '工作消息', exact: true })).toBeVisible()
const workReady = (page) => expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible()
const tab = (name) => (page) =>
  page
    .locator('button, [role="tab"]')
    .filter({ hasText: new RegExp(`^${name}$`) })
    .click()
const button = (name) => (page) => page.getByRole('button', { name, exact: true }).click()
const dialog = (name) => (page) => expect(page.getByRole('dialog', { name })).toBeVisible()
const workPath = (role) => `/work/${ids[role].work}`
const reportPath = (kind = 'daily') => `/reports/${ids.employee[kind]}`
const showReports = (kind) => async (page) => {
  await tab('全部报告')(page)
  await expect(page.getByRole('button', { name: '全部报告', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const selectedKind = page.getByRole('button', {
    name: kind === 'weekly' ? '周报' : '日报',
    exact: true,
  })
  if (kind === 'weekly') await selectedKind.click()
  await expect(selectedKind).toHaveAttribute('aria-pressed', 'true')
  const list = page.locator('[aria-label="报告列表"]')
  await expect(list.locator(`a[href="${reportPath(kind)}"]`)).toBeVisible()
  await expect(list.getByText('正在读取报告…', { exact: true })).toHaveCount(0)
}
const common = (role) => [
  routeCase('assistant-new', '/assistant?new=1', assistantReady),
  routeCase('assistant-chat', `/assistant/${ids[role].conversation}`, assistantReady),
  routeCase('message-source', `/messages/${ids[role].message}`, workReady),
  routeCase('work', '/work', textReady('我的工作')),
  routeCase('work-detail', workPath(role), workReady),
  routeCase('work-history', `${workPath(role)}?revision=1`, workReady),
  routeCase('account', '/settings/account', textReady('账户')),
  routeCase('appearance', '/settings/appearance', textReady('外观')),
  routeCase('rules', '/settings/rules', textReady('汇报规则')),
  routeCase('support', '/settings/support', textReady('问题反馈')),
]
const admin = [
  routeCase('team-work', '/team', textReady('团队看板')),
  routeCase('team-updated', '/team?scope=updated', textReady('团队看板')),
  routeCase('team-reports', '/team?view=reports', textReady('团队看板')),
  routeCase('members', '/members', textReady('成员管理')),
  routeCase('models', '/settings/models', textReady('模型服务管理')),
  routeCase('models-routing', '/settings/models', textReady('模型服务管理'), tab('用途分配')),
  routeCase('model-usage', '/settings/usage', textReady('模型用量')),
  routeCase('voiceprints', '/settings/voiceprints', textReady('公司声纹')),
  routeCase('login-methods', '/settings/login', textReady('登录方式')),
  routeCase('report-detail', reportPath(), workReady),
]
const employee = [
  routeCase('reports-todo', '/reports', textReady('我的报告')),
  routeCase('reports-all', '/reports', textReady('我的报告'), showReports('daily')),
  routeCase('reports-weekly', '/reports', textReady('我的报告'), showReports('weekly')),
  routeCase('report-detail', reportPath(), workReady),
  routeCase('report-draft', reportPath('weekly'), workReady),
]

async function settle(page) {
  await page.waitForLoadState('networkidle')
  await page.evaluate(() => document.fonts.ready)
  await expect(page.getByText('正在加载页面', { exact: true })).toHaveCount(0)
}

async function theme(page, value) {
  await page.getByRole('button', { name: 'Noria 外观', exact: true }).click()
  const modal = page.getByRole('dialog', { name: 'Noria 外观', exact: true })
  await modal.getByRole('button', { name: value === 'dark' ? '深色' : '浅色', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(modal).toHaveCount(0)
}

async function login(page, role) {
  await page.goto(state.origin)
  await page.getByRole('button', { name: /直接登录/ }).click()
  await page.getByLabel('账号', { exact: true }).fill(state.users[role].username)
  await page.getByLabel('密码', { exact: true }).fill(state.users[role].password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('navigation', { name: '工作空间' })).toBeAttached()
  await settle(page)
}

async function record(page, role, item, variant, extra = {}) {
  const file = `${role}--${item.name}--${variant}.png`
  const metrics = await page.evaluate(() => {
    const visible = (node) => {
      const bounds = node.getBoundingClientRect()
      return bounds.width > 0 && bounds.height > 0 && getComputedStyle(node).visibility !== 'hidden'
    }
    const geometry = (node) => {
      const r = node.getBoundingClientRect()
      const style = getComputedStyle(node)
      return {
        text: (node.getAttribute('aria-label') || node.textContent || '').trim().slice(0, 100),
        x: r.x,
        y: r.y,
        width: r.width,
        height: r.height,
        font: style.fontSize,
        padding: style.padding,
        margin: style.margin,
      }
    }
    return {
      viewport: [innerWidth, innerHeight],
      pageOverflow: document.documentElement.scrollWidth - innerWidth,
      headings: [...document.querySelectorAll('h1,h2,h3')].filter(visible).map(geometry),
      alerts: [...document.querySelectorAll('[role="alert"]')].filter(visible).map(geometry),
      scrollers: [...document.querySelectorAll('[data-scroll-container]')].map((node) => ({
        ...geometry(node),
        scrollTop: node.scrollTop,
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
      })),
    }
  })
  await page.screenshot({ path: resolve(output, 'screenshots', file), animations: 'disabled' })
  results = results.filter((result) => result.file !== file)
  results.push({ role, name: item.name, variant, path: item.path, file, ...extra, ...metrics })
  await writeFile(resolve(output, 'manifest.json'), JSON.stringify(results, null, 2))
  console.log(file)
}

async function captureCase(page, role, item, viewport, color, options = {}) {
  const [width, height] = typeof viewport === 'string' ? sizes[viewport] : [viewport, 1000]
  const variant = `${typeof viewport === 'string' ? viewport : `width-${viewport}`}-${color}`
  if (alreadyCaptured(role, item.name, variant)) return
  let release = () => {}
  const errors = []
  const onError = (error) => errors.push(error.message)
  page.on('pageerror', onError)
  try {
    await page.setViewportSize({ width, height })
    // Set the persisted theme before opening a dialog, so theme controls never steal its focus.
    await page.goto(state.origin + '/assistant?new=1')
    await assistantReady(page)
    await settle(page)
    await theme(page, color)
    if (item.mock) release = await item.mock(page)
    await page.goto(state.origin + item.path)
    await item.ready(page)
    if (!item.loading) await settle(page)
    if (item.action) await item.action(page)
    if (item.after) await item.after(page)
    if (!item.loading) await settle(page)
    if (errors.length) throw new Error(`Uncaught page error: ${errors.join('; ')}`)
    await page.mouse.move(0, height - 1)
    await record(page, role, item, variant, {
      status: 'captured',
      fixture: item.mock ? 'intercepted-state' : 'isolated-api',
    })
    if (options.sections && !item.action) {
      const scroller = page.locator('[data-scroll-container]').last()
      if (await scroller.count()) {
        const range = await scroller.evaluate((node) => ({
          step: Math.floor(node.clientHeight * 0.8),
          end: node.scrollHeight - node.clientHeight,
        }))
        if (range.step > 0 && range.end > 100) {
          const offsets = new Set()
          for (let y = range.step; y < range.end; y += range.step) offsets.add(y)
          offsets.add(range.end)
          let section = 0
          for (const offset of offsets) {
            await scroller.evaluate((node, y) => node.scrollTo(0, y), offset)
            await record(page, role, item, `${variant}-section-${++section}`, {
              status: 'captured',
              fixture: 'isolated-api',
            })
          }
        }
      }
    }
  } catch (error) {
    failures.push({ role, name: item.name, variant, error: error.message })
    await record(page, role, item, variant, { status: 'failed', error: error.message })
    console.error(`FAILED ${role}/${item.name}/${variant}: ${error.message}`)
  } finally {
    await release()
    page.off('pageerror', onError)
  }
}

function intercept(pattern, payload) {
  return async (page) => {
    const handler = (route) => route.fulfill({ json: payload })
    await page.route(pattern, handler)
    return () => page.unroute(pattern, handler)
  }
}

function supplementary(role) {
  const openWorkMenu = async (page) => {
    await button('管理工作')(page)
    await page.getByRole('menuitem', { name: '编辑工作属性', exact: true }).click()
  }
  const cases = [
    routeCase('work-create', '/work', textReady('我的工作'), button('新建工作')),
    routeCase('work-editor', workPath(role), workReady, button('编辑内容')),
    routeCase('work-properties', workPath(role), workReady, openWorkMenu),
    routeCase('work-no-results', '/work?q=没有这项工作', textReady('我的工作')),
    routeCase('account-password', '/settings/account', textReady('账户'), (page) =>
      page.locator('summary').filter({ hasText: '修改密码' }).click(),
    ),
    routeCase('appearance-dialog', '/assistant?new=1', assistantReady, button('Noria 外观')),
    routeCase('assistant-permission', '/assistant?new=1', assistantReady, (page) =>
      page.getByRole('button', { name: /执行权限|自动审核/ }).click(),
    ),
    routeCase('assistant-persona', '/assistant?new=1', assistantReady, (page) =>
      page.getByRole('button', { name: /选择人设：/ }).click(),
    ),
    routeCase(
      'assistant-history',
      `/assistant/${ids[role].conversation}`,
      assistantReady,
      button('会话列表'),
    ),
    routeCase('search-dialog', '/work', textReady('我的工作'), (page) =>
      page.keyboard.press('ControlOrMeta+k'),
    ),
    routeCase(
      'desktop-connect-invalid',
      '/desktop/connect?request=invalid',
      textReady('连接 Noria 桌面端'),
      undefined,
      { dark: true },
    ),
  ]
  if (role === 'admin') {
    cases.push(
      routeCase('member-create', '/members', textReady('成员管理'), button('添加成员')),
      ...['编辑姓名', '重置密码', '删除账号'].map((name, index) =>
        routeCase(
          ['member-edit', 'member-password', 'member-delete'][index],
          '/members',
          textReady('成员管理'),
          async (page) => {
            await page.getByRole('button', { name: '更多操作' }).first().click()
            await page.getByRole('menuitem', { name, exact: true }).click()
          },
        ),
      ),
      routeCase('members-search-focus', '/members', textReady('成员管理'), (page) =>
        page.getByLabel('搜索成员').focus(),
      ),
      routeCase(
        'team-work-drawer',
        `/team?record=${ids.employee.work}`,
        dialog('工作详情'),
        undefined,
        { dark: true },
      ),
      routeCase(
        'team-report-drawer',
        `/team?view=reports&record=${ids.employee.daily}`,
        dialog('报告详情'),
        undefined,
        { dark: true },
      ),
      routeCase('team-expanded-filters', '/team', textReady('团队看板'), async (page) => {
        const toggle = page.getByRole('button', { name: /^筛选/ })
        if (page.viewportSize().width <= 760) {
          await expect(toggle).toBeVisible()
          await toggle.click()
        } else await expect(toggle).toBeHidden()
        await expect(page.getByRole('combobox', { name: '选择员工', exact: true })).toBeVisible()
      }),
      routeCase('models-new', '/settings/models', textReady('模型服务管理'), (page) =>
        page.getByRole('button', { name: '添加服务', exact: true }).first().click(),
      ),
      routeCase('voiceprint-upload', '/settings/voiceprints', textReady('公司声纹'), (page) =>
        page.getByRole('button', { name: '上传录音', exact: true }).last().click(),
      ),
    )
  } else {
    cases.push(
      routeCase('report-editor', reportPath('weekly'), workReady, button('编辑草稿')),
      routeCase('report-submit', reportPath('weekly'), workReady, button('提交报告')),
      routeCase('reports-schedule', '/reports', textReady('我的报告'), button('汇报安排')),
      routeCase('notifications', '/reports', textReady('我的报告'), async (page) => {
        if (await page.getByRole('button', { name: '展开导航', exact: true }).isVisible())
          await button('展开导航')(page)
        await page.getByRole('button', { name: /汇报通知/ }).click()
      }),
    )
  }
  return cases
}

async function configureSyntheticModel(page) {
  return page.evaluate(async () => {
    const identity = await (await fetch('/api/v1/auth/me')).json()
    const listing = await (await fetch('/api/v1/settings/model-services')).json()
    const name = 'UI 排版测试服务'
    if (listing.services?.some((service) => service.name === name)) return
    const response = await fetch('/api/v1/settings/model-services', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': identity.csrf,
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify({
        name,
        baseUrl: 'https://example.com/v1',
        apiKey: 'synthetic-ui-layout-key',
        models: [
          {
            id: 'chat',
            model: 'synthetic-chat',
            protocol: 'chat',
            protocolMode: 'manual',
            streaming: true,
            contextWindow: 1000000,
            presets: [],
          },
        ],
        expectedRevision: listing.revision ?? 0,
      }),
    })
    if (!response.ok) throw new Error(`Synthetic model fixture failed: ${response.status}`)
  })
}

async function selectSyntheticModel(page) {
  const select = page.getByRole('combobox', { name: '选择模型服务', exact: true })
  if (await select.isVisible()) {
    const value = await select
      .getByRole('option', { name: /UI 排版测试服务/ })
      .getAttribute('value')
    if (!value) throw new Error('Synthetic model service option is missing')
    await select.selectOption(value)
  } else await page.getByRole('button', { name: /UI 排版测试服务/ }).click()
  await expect(page.getByLabel('服务名称')).toBeVisible()
}

const include = (item) => !selected || selected.includes(item.name)
const alreadyCaptured = (role, name, variant) =>
  resume &&
  results.some(
    (result) =>
      result.role === role &&
      result.name === name &&
      result.variant === variant &&
      result.status === 'captured',
  )
try {
  for (const role of ['admin', 'employee']) {
    const context = await browser.newContext({ locale: 'zh-CN', reducedMotion: 'reduce' })
    const page = await context.newPage()
    page.setDefaultTimeout(10_000)
    await login(page, role)
    const pages = [...common(role), ...(role === 'admin' ? admin : employee)]
    for (const item of pages.filter(include)) {
      for (const viewport of ['desktop', 'mobile'])
        for (const color of ['light', 'dark'])
          await captureCase(page, role, item, viewport, color, { sections: color === 'light' })
    }
    for (const item of supplementary(role).filter(include)) {
      for (const viewport of ['desktop', 'mobile'])
        for (const color of item.dark ? ['light', 'dark'] : ['light'])
          await captureCase(page, role, item, viewport, color)
    }
    for (const item of pages.filter(
      (item) =>
        ['work-history', 'models', 'members', 'reports-todo'].includes(item.name) && include(item),
    )) {
      for (const width of [360, 768, 1024]) await captureCase(page, role, item, width, 'light')
    }
    if (role === 'admin') {
      await page.goto(state.origin + '/settings/models')
      await settle(page)
      await configureSyntheticModel(page)
      const configured = [
        routeCase(
          'models-configured',
          '/settings/models',
          textReady('模型服务管理'),
          async (page) => {
            await selectSyntheticModel(page)
          },
        ),
        routeCase(
          'models-routing-configured',
          '/settings/models',
          textReady('模型服务管理'),
          tab('用途分配'),
        ),
        routeCase(
          'model-test-dialog',
          '/settings/models',
          textReady('模型服务管理'),
          async (page) => {
            await selectSyntheticModel(page)
            await page.getByRole('button', { name: '测试 synthetic-chat', exact: true }).click()
            await dialog('测试模型配置')(page)
          },
        ),
      ]
      for (const item of configured.filter(include))
        for (const viewport of ['desktop', 'mobile'])
          for (const color of item.name === 'model-test-dialog' ? ['light'] : ['light', 'dark'])
            await captureCase(page, role, item, viewport, color)
      const empty = routeCase('members-empty', '/members', textReady('成员管理'), undefined, {
        mock: intercept(/\/api\/v1\/members(?:\?|$)/, { items: [], nextCursor: null }),
      })
      const error = routeCase('source-error', '/messages/ui-layout-missing', (page) =>
        expect(page.getByRole('alert')).toBeVisible(),
      )
      const loading = routeCase(
        'members-loading',
        '/members',
        (page) => expect(page.getByText('正在读取成员…', { exact: true })).toBeVisible(),
        undefined,
        {
          loading: true,
          mock: async (page) => {
            let finish
            const gate = new Promise((resolve) => {
              finish = resolve
            })
            const pattern = /\/api\/v1\/members(?:\?|$)/
            const pending = new Set()
            const handler = (route) => {
              const operation = gate.then(() => route.continue())
              pending.add(operation)
              return operation.finally(() => pending.delete(operation))
            }
            await page.route(pattern, handler)
            return async () => {
              finish()
              // Removing the handler first allows Playwright to continue the same request twice.
              await Promise.all([...pending])
              await page.waitForLoadState('networkidle')
              await page.unroute(pattern, handler)
            }
          },
        },
      )
      const memberError = routeCase(
        'members-error',
        '/members',
        (page) => expect(page.getByRole('alert')).toBeVisible(),
        undefined,
        {
          mock: async (page) => {
            const pattern = /\/api\/v1\/members(?:\?|$)/
            const handler = (route) => route.fulfill({ status: 503, json: {} })
            await page.route(pattern, handler)
            return () => page.unroute(pattern, handler)
          },
        },
      )
      const validation = routeCase(
        'member-field-errors',
        '/members',
        textReady('成员管理'),
        async (page) => {
          await button('添加成员')(page)
          const modal = page.getByRole('dialog', { name: '添加成员', exact: true })
          await modal.getByRole('button', { name: '保存', exact: true }).click()
          await expect(modal.getByLabel('姓名')).toHaveAttribute('aria-invalid', 'true')
        },
      )
      for (const item of [empty, error, loading, memberError, validation].filter(include))
        for (const viewport of ['desktop', 'mobile'])
          await captureCase(page, role, item, viewport, 'light')
    }
    await context.close()
  }
  for (const color of ['light', 'dark']) {
    for (const viewport of ['desktop', 'mobile']) {
      const [width, height] = sizes[viewport]
      const context = await browser.newContext({
        viewport: { width, height },
        colorScheme: color,
        reducedMotion: 'reduce',
      })
      const page = await context.newPage()
      const publicCases = [
        routeCase('login-cover', '/', (page) =>
          expect(page.getByRole('button', { name: /打开书本/ })).toBeVisible(),
        ),
        routeCase(
          'login-open',
          '/',
          (page) => expect(page.getByRole('button', { name: /直接登录/ })).toBeVisible(),
          (page) => page.getByRole('button', { name: /直接登录/ }).click(),
        ),
        routeCase(
          'login-validation',
          '/',
          () => {},
          async (page) => {
            await page.getByRole('button', { name: /直接登录/ }).click()
            await button('登录')(page)
            await expect(page.getByText('请输入账号', { exact: true })).toBeVisible()
          },
        ),
        routeCase('dingtalk-result', '/?dingtalk=failed&reason=expired', (page) =>
          expect(page.getByRole('alert')).toBeVisible(),
        ),
      ]
      for (const item of publicCases.filter(include)) {
        if (alreadyCaptured('public', item.name, `${viewport}-${color}`)) continue
        try {
          await page.goto(state.origin + item.path)
          await item.ready(page)
          if (item.action) await item.action(page)
          await settle(page)
          await record(page, 'public', item, `${viewport}-${color}`, {
            status: 'captured',
            fixture: 'isolated-api',
          })
        } catch (error) {
          failures.push({ role: 'public', name: item.name, error: error.message })
          await record(page, 'public', item, `${viewport}-${color}`, {
            status: 'failed',
            error: error.message,
          })
        }
      }
      await context.close()
    }
  }
} finally {
  await browser.close()
  await writeFile(
    resolve(output, 'capture-results.json'),
    JSON.stringify(
      {
        screenshots: results.filter((result) => result.status === 'captured').length,
        failures: results
          .filter((result) => result.status === 'failed')
          .map(({ role, name, variant, error }) => ({ role, name, variant, error })),
        limitations: [
          'Chromium simulated viewports; no physical phone.',
          'Synthetic data; no real LLM, DingTalk OAuth or desktop approval executed.',
          'Empty, loading and service-error states are explicitly labeled response fixtures.',
        ],
      },
      null,
      2,
    ),
  )
}
if (failures.length || results.some((result) => result.status === 'failed')) process.exitCode = 1
