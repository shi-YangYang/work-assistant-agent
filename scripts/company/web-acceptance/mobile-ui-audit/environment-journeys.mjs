import { chromium, expect } from '@playwright/test'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { isolatedEnvironment } from '../../../../tests/e2e/web/fixtures/environment.mjs'
const state = isolatedEnvironment()
const output = resolve(process.env.SPEC073_OUTPUT, '../journeys')
mkdirSync(output, { recursive: true })
const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  deviceScaleFactor: 1,
})
const page = await context.newPage()
page.setDefaultTimeout(10000)
let currentRole = 'anonymous'
const results = [],
  shots = [],
  requests = [],
  errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('response', (r) => {
  const path = new URL(r.url()).pathname
  if (path.startsWith('/api/v1/'))
    requests.push({ method: r.request().method(), path, status: r.status() })
})
async function snap(name, note = '') {
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  )
  await page.waitForTimeout(180)
  await page.screenshot({ path: resolve(output, name + '.png') })
  shots.push({
    name,
    note,
    url: page.url(),
    viewport: page.viewportSize(),
    role: currentRole,
    browser: 'Chromium',
    touch: true,
    dataMode: /M18-(test-result|catalog)/.test(name) ? 'controlled-ui' : 'owned-real-api',
    theme: await page.evaluate(() => document.documentElement.dataset.theme),
  })
  save()
}
function save() {
  writeFileSync(
    resolve(output, `journeys-${process.argv[2] || 'initial'}-results.json`),
    JSON.stringify({ results, shots, requests, errors }, null, 2),
  )
}
async function run(id, fn) {
  try {
    await fn()
    results.push({ id, status: 'PASS' })
  } catch (e) {
    results.push({ id, status: 'FAIL', error: e.message })
    await snap(id + '-failure')
  }
  save()
}
async function login(role) {
  currentRole = role
  await page.goto(state.origin)
  await page.getByRole('button', { name: /直接登录/ }).click()
  await page.getByLabel('账号', { exact: true }).fill(state.users[role].username)
  await page.getByLabel('密码', { exact: true }).fill(state.users[role].password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(
    page.getByRole('navigation', { name: '工作空间', includeHidden: true }),
  ).toBeAttached()
}
async function api(path, method = 'GET', body) {
  return page.evaluate(
    async ({ path, method, body }) => {
      const me = await (await fetch('/api/v1/auth/me')).json()
      const r = await fetch('/api/v1' + path, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': me.csrf,
          'Idempotency-Key': crypto.randomUUID(),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      })
      return { status: r.status, data: await r.json() }
    },
    { path, method, body },
  )
}

const role = process.env.AUDIT_ROLE || 'peer'
await login(role)
const fixtures = JSON.parse(
  readFileSync(resolve(process.env.SPEC073_OUTPUT, 'peer-layout.json'), 'utf8'),
).peer
if (process.argv[2] === 'debugreport') {
  await page.goto(state.origin + '/reports/' + fixtures.workflow + '?edit=1')
  await page.locator('textarea').first().waitFor()
  console.log(await page.locator('label').allTextContents())
  console.log(
    await page
      .locator('textarea')
      .evaluateAll((ns) =>
        ns.map((n) => ({ outer: n.outerHTML, labels: [...n.labels].map((x) => x.textContent) })),
      ),
  )
}
if (process.argv[2] === 'business') {
  await run('J07-work-edit-save-refresh', async () => {
    await page.goto(state.origin + '/work')
    await page.getByRole('button', { name: '新建工作', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '新建工作' })
    await dialog.getByRole('textbox', { name: '工作事项' }).fill('SPEC073 真实手机工作连续旅程')
    await dialog.getByRole('button', { name: '创建工作', exact: true }).click()
    await page.getByRole('button', { name: '编辑内容', exact: true }).click()
    await page
      .getByRole('textbox', { name: '工作正文' })
      .fill('手机端合成任务：保存内容后刷新，确认持久化结果。')
    await page.getByRole('button', { name: '保存内容', exact: true }).click()
    await expect(page.getByRole('button', { name: '编辑内容', exact: true })).toBeVisible()
    const id = new URL(page.url()).pathname.split('/').at(-1)
    const stored = await api('/work-items/' + id)
    expect(stored.data.bodyText).toContain('手机端合成任务')
    await page.reload()
    await expect(
      page
        .getByRole('textbox', { name: '工作正文' })
        .getByText('手机端合成任务：保存内容后刷新，确认持久化结果。', { exact: true }),
    ).toBeVisible()
    await snap('J07-work-persisted', '真实UI创建、编辑、保存和刷新，API回读正文一致')
    await page
      .getByRole('region', { name: '修改记录' })
      .getByRole('link', { name: '查看此版本' })
      .last()
      .click()
    await expect(page.getByRole('link', { name: '返回最新版本' })).toBeVisible()
    await snap('J07-work-history', '真实历史版本与返回入口')
    await page.getByRole('link', { name: '返回最新版本' }).click()
  })
  await run('J08-report-edit-submit-refresh', async () => {
    await page.goto(state.origin + '/reports/' + fixtures.workflow)
    await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
    await page.getByLabel(/^完成的工作/).fill('SPEC073 已完成手机布局检查，记录可复现证据。')
    await page.getByRole('button', { name: '保存草稿', exact: true }).click()
    await expect(page.getByText('草稿已保存', { exact: true })).toBeVisible()
    await snap('J08-report-edited', '真实草稿编辑保存；手机主操作栏')
    await page.getByRole('button', { name: '提交报告', exact: true }).click()
    await snap('J08-report-submit-confirm', '真实提交确认弹窗')
    await page.getByRole('dialog').getByRole('button', { name: '确认提交', exact: true }).click()
    await expect(page.getByText('已提交第 2 版', { exact: true })).toBeVisible()
    const read = await api('/reports/' + fixtures.workflow)
    expect(read.data.publishedRevision).toBe(2)
    await page.reload()
    await expect(
      page.getByText('SPEC073 已完成手机布局检查，记录可复现证据。', { exact: true }),
    ).toBeVisible()
    await snap('J08-report-submitted', 'API publishedRevision=2，刷新内容仍存在')
    await page.getByRole('button', { name: /^第 2 版/ }).click()
    await expect(page.getByRole('dialog', { name: '已提交 · 第 2 版' })).toBeVisible()
    await snap('J08-report-history')
    await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
    await page.getByRole('link', { name: '返回我的报告', exact: true }).click()
    await snap('J08-report-return')
  })
}
if (process.argv[2] === 'uploads') {
  await run('J03-real-upload-retry-delete-send-refresh', async () => {
    await page.goto(state.origin + '/assistant?new=1')
    await page.getByRole('textbox', { name: '工作消息' }).waitFor()
    let failOnce = true
    await page.route('**/api/v1/uploads', async (route) => {
      if (route.request().method() === 'POST' && failOnce) {
        failOnce = false
        await route.fulfill({ status: 503, json: { detail: '受控上传失败，请重试' } })
      } else await route.continue()
    })
    const file = {
      name: 'SPEC073-重试文件.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('SPEC073_MARKER_RETRY 已完成需求核对。'),
    }
    await page.locator('input[type=file]').nth(1).setInputFiles(file)
    await expect(page.getByRole('button', { name: '重试上传' + file.name })).toBeVisible()
    await snap('J03-upload-error', '仅首个上传HTTP返回受控503；随后重试走真实API')
    await page.getByRole('button', { name: '重试上传' + file.name }).click()
    await expect(page.getByRole('button', { name: '重试上传' + file.name })).toHaveCount(0)
    await page.unroute('**/api/v1/uploads')
    await snap('J03-upload-retry-success')
    const removed = page.waitForResponse(
      (r) =>
        r.request().method() === 'DELETE' &&
        new URL(r.url()).pathname.startsWith('/api/v1/uploads/'),
    )
    await page.getByRole('button', { name: '移除' + file.name }).click()
    expect((await removed).status()).toBe(200)
    await expect(page.getByRole('button', { name: '移除' + file.name })).toHaveCount(0)
    await snap('J03-upload-delete', '真实DELETE已返回200且卡片移除')
    const docs = Array.from({ length: 7 }, (_, i) => ({
      name: `合成材料-${i + 1}.txt`,
      mimeType: 'text/plain',
      buffer: Buffer.from(`SPEC073_MARKER_BATCH${i + 1} 第${i + 1}份合成材料。`),
    }))
    await page.locator('input[type=file]').nth(1).setInputFiles(docs.slice(0, 4))
    await page.locator('input[type=file]').nth(1).setInputFiles(docs.slice(4))
    await page
      .locator('input[type=file]')
      .first()
      .setInputFiles({
        name: '合成图片.png',
        mimeType: 'image/png',
        buffer: Buffer.from(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9i8AAAAASUVORK5CYII=',
          'base64',
        ),
      })
    await expect(page.getByLabel('上传中', { exact: true })).toHaveCount(0, { timeout: 20000 })
    await snap('J03-batch-mixed-eight', '两批7文档+1图片，真实即时上传完成')
    await page.getByRole('textbox', { name: '工作消息' }).fill('请确认上传的材料，用一句话回复。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.getByText(/受控 UI 验收回复/).last()).toBeVisible({ timeout: 60000 })
    await expect(page.getByRole('button', { name: '中断', exact: true })).toHaveCount(0, {
      timeout: 30000,
    })
    const url = page.url()
    await snap('J03-real-completed', '真实UI发送→真实任务/附件准备→localhost固定模型→持久化完成')
    await page.goto(state.origin + '/work')
    await page.goto(url)
    await page.reload()
    await expect(page.getByText(/受控 UI 验收回复/).last()).toBeVisible()
    await snap('J03-real-refresh')
    await page
      .getByRole('textbox', { name: '工作消息' })
      .fill('请再看第一批材料，确认较早附件仍可见。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.getByRole('button', { name: '中断', exact: true })).toHaveCount(0, {
      timeout: 60000,
    })
    await expect(page.getByText(/受控 UI 验收回复/)).toHaveCount(2, { timeout: 30000 })
    await snap('J03-real-followup', '第二条真实消息完成；provider日志检查早期标记送入模型')
  })
}
if (process.argv[2] === 'models') {
  await run('M18-model-service-config-routing', async () => {
    await page.goto(state.origin + '/settings/models')
    await page.getByRole('button', { name: '添加服务', exact: true }).first().click()
    await page
      .getByLabel('服务名称', { exact: true })
      .fill('SPEC073 长模型服务名称检查：移动端测试与用途配置')
    await page.getByLabel('Base URL', { exact: true }).fill('https://example.com/v1')
    await page.getByLabel('API 密钥', { exact: true }).fill('synthetic-not-a-real-key')
    await snap('M18-connection-390', '真实隔离公司，示例地址保存不触发外部请求')
    await page.getByRole('button', { name: '手动添加', exact: true }).click()
    await snap('M18-add-model-dialog')
    await page
      .getByRole('dialog', { name: '手动添加模型' })
      .getByLabel('模型 ID')
      .fill('synthetic-model-long-name-for-mobile-ui-review')
    await page
      .getByRole('dialog', { name: '手动添加模型' })
      .getByRole('button', { name: '添加模型', exact: true })
      .click()
    const settings = page.getByRole('dialog', {
      name: '设置 synthetic-model-long-name-for-mobile-ui-review',
    })
    await settings.getByRole('combobox', { name: '接口协议' }).selectOption('chat')
    for (const effort of ['low', 'medium', 'high', 'max', 'ultra', 'extended']) {
      await settings.getByLabel('可选思考强度').fill(effort)
      await settings.getByLabel('可选思考强度').press('Enter')
    }
    await snap('M18-model-options-tags-390')
    await page.setViewportSize({ width: 320, height: 568 })
    await snap('M18-model-options-320')
    await page.setViewportSize({ width: 430, height: 932 })
    await snap('M18-model-options-430')
    await page.setViewportSize({ width: 390, height: 480 })
    await snap('M18-model-options-lowheight')
    await settings.getByRole('button', { name: '完成', exact: true }).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '保存服务', exact: true }).click()
    await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('')
    const stored = await api('/settings/model-services')
    expect(stored.status).toBe(200)
    const service = stored.data.services.find((s) => s.name.startsWith('SPEC073'))
    expect(service.models[0].reasoning.efforts).toHaveLength(6)
    await page.reload()
    await expect(page.getByLabel('服务名称')).toHaveValue(service.name)
    await snap('M18-saved-service', '真实POST保存后刷新，API密钥不回显')
    await page
      .getByRole('button', {
        name: '测试 synthetic-model-long-name-for-mobile-ui-review',
        exact: true,
      })
      .click()
    await snap('M18-test-confirm')
    await page.route('**/api/v1/settings/model-services/test', async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        json: {
          draftVersion: body.draftVersion,
          service: body.name,
          model: service.models[0].model,
          time: new Date().toISOString(),
          elapsedMs: 25,
          checks: [
            { name: '文字回复', state: 'passed', message: '受控UI结果' },
            {
              name: '图片识别',
              state: 'failed',
              message: '受控连接错误：服务暂时不可用，请检查配置后重试。',
            },
            { name: '工具调用', state: 'untested' },
          ],
          usage: null,
        },
      })
    })
    await page
      .getByRole('dialog', { name: '测试模型配置' })
      .getByRole('button', { name: '开始测试', exact: true })
      .click()
    await expect(page.getByRole('dialog', { name: '模型测试结果' })).toBeVisible()
    await snap('M18-test-result', '测试响应受控，不真实调用模型；检查成功失败混合文案布局')
    await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).last().click()
    await page.unroute('**/api/v1/settings/model-services/test')
    await page.getByRole('tab', { name: '用途分配', exact: true }).click()
    await page
      .getByRole('combobox', { name: /使用的模型/ })
      .first()
      .selectOption(service.id + '/' + service.models[0].id)
    await page.getByRole('button', { name: '保存用途分配', exact: true }).click()
    await expect(page.getByText('用途分配已保存', { exact: true })).toBeVisible()
    expect((await api('/settings/model-routing')).data.assistant.serviceId).toBe(service.id)
    await snap('M18-routing-saved-390', '真实PUT保存用途配置、API回读一致')
    await page.setViewportSize({ width: 320, height: 568 })
    await snap('M18-routing-320')
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.evaluate(() => {
      localStorage.setItem('paa.company.theme', 'dark')
      document.documentElement.dataset.theme = 'dark'
    })
    await snap('M18-routing-dark')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ colorScheme: 'light' })
    await page.evaluate(() => {
      localStorage.removeItem('paa.company.theme')
      delete document.documentElement.dataset.theme
    })
    await page.getByRole('tab', { name: '服务配置', exact: true }).click()
    await page.getByRole('button', { name: '删除当前模型服务', exact: true }).click()
    await snap('M18-remove-service-dialog')
    await page.getByRole('dialog').getByRole('button', { name: '继续编辑', exact: true }).click()
  })
}
if (process.argv[2] === 'announcements') {
  await run('J10-announcement-publish-edit-read-delete', async () => {
    await page.goto(state.origin + '/announcement-management')
    await page.getByRole('link', { name: '发布公告', exact: true }).click()
    await page.getByLabel('公告标题', { exact: true }).fill('SPEC073 真实公告发布与删除连续旅程')
    await page
      .getByRole('textbox', { name: '公告正文', exact: true })
      .fill(
        '# 仅用于隔离验收\n\n手机端通知交互测试，不向真实员工发送。\n\n' +
          '长段落验证阅读和底部操作。'.repeat(35),
      )
    await snap('J10-announcement-editor')
    await page.getByRole('button', { name: '发布', exact: true }).click()
    await page.waitForURL(/announcement-management\/[a-f0-9-]+$/)
    const id = new URL(page.url()).pathname.split('/').at(-1)
    await snap('J10-announcement-published')
    await page.getByRole('link', { name: '编辑', exact: true }).click()
    await page
      .getByLabel('公告标题', { exact: true })
      .fill('SPEC073 真实公告发布与删除连续旅程（已编辑）')
    await page.getByRole('button', { name: '保存修改', exact: true }).click()
    await expect(
      page.getByRole('heading', {
        name: 'SPEC073 真实公告发布与删除连续旅程（已编辑）',
        exact: true,
      }),
    ).toBeVisible()
    const stored = await api('/announcements/' + id + '?management=true')
    expect(stored.data.revision).toBe(2)
    await context.clearCookies()
    await login('peer')
    await page.goto(state.origin + '/notifications?tab=announcements')
    await page.getByRole('tab', { name: /公告/ }).click()
    const row = page
      .locator('div')
      .filter({
        has: page.getByRole('link', { name: /SPEC073 真实公告发布与删除连续旅程（已编辑）/ }),
      })
      .filter({ has: page.getByRole('button', { name: '标为已读', exact: true }) })
      .last()
    await row.getByRole('button', { name: '标为已读', exact: true }).click()
    const list = await api('/announcements?state=published&cursor=0')
    expect(list.data.items.find((x) => x.id === id).unread).toBe(false)
    await snap('J10-announcement-mark-read')
    await page.getByRole('link', { name: /SPEC073 真实公告发布与删除连续旅程（已编辑）/ }).click()
    await snap('J10-announcement-user-detail')
    await page.getByRole('link', { name: /返回通知/ }).click()
    await context.clearCookies()
    await login('admin')
    await page.goto(state.origin + '/announcement-management')
    const target = page
      .getByRole('link', { name: /SPEC073 真实公告发布与删除连续旅程（已编辑）/ })
      .locator('..')
    await target.getByRole('button', { name: '删除', exact: true }).click()
    await snap('J10-announcement-delete-confirm')
    await page
      .getByRole('dialog', { name: '删除公告' })
      .getByRole('button', { name: '删除', exact: true })
      .click()
    await expect(
      page.getByRole('link', { name: /SPEC073 真实公告发布与删除连续旅程（已编辑）/ }),
    ).toHaveCount(0)
    await page.reload()
    await expect(
      page.getByRole('link', { name: /SPEC073 真实公告发布与删除连续旅程（已编辑）/ }),
    ).toHaveCount(0)
    expect((await api('/announcements/' + id + '?management=true')).status).toBe(404)
    await snap('J10-announcement-deleted', '真实创建、修改、用户已读、删除；刷新列表移除，详情404')
  })
}
if (process.argv[2] === 'model-extra') {
  await run('M18-existing-remove-cancel-image-catalog', async () => {
    await page.goto(state.origin + '/settings/models')
    await page.getByRole('button', { name: '删除当前模型服务', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: '继续编辑', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button', { name: '手动添加', exact: true }).click()
    await page
      .getByRole('dialog', { name: '手动添加模型' })
      .getByLabel('模型 ID')
      .fill('wan2.7-image')
    await page
      .getByRole('dialog', { name: '手动添加模型' })
      .getByRole('button', { name: '添加模型', exact: true })
      .click()
    const settings = page.getByRole('dialog', { name: '设置 wan2.7-image' })
    await settings.getByRole('combobox', { name: '接口协议' }).selectOption('dashscope-image')
    await settings.getByRole('combobox', { name: '图片尺寸' }).selectOption('fixed')
    for (const size of ['1024*1024', '1536*1024', '1024*1536', '2048*2048']) {
      await settings.getByLabel('可选尺寸', { exact: true }).fill(size)
      await settings.getByLabel('可选尺寸', { exact: true }).press('Enter')
    }
    await snap('M18-image-options')
    await page.setViewportSize({ width: 320, height: 568 })
    await snap('M18-image-options-320')
    await settings.getByRole('button', { name: '完成', exact: true }).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '保存服务', exact: true }).click()
    await page.route('**/api/v1/settings/model-services/models', async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        json: {
          draftVersion: body.draftVersion,
          source: '受控UI模型目录',
          truncated: false,
          models: Array.from(
            { length: 18 },
            (_, i) => 'catalog-model-' + i + '-long-mobile-identifier-2026',
          ),
        },
      })
    })
    await page.getByRole('button', { name: '获取模型', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await snap('M18-catalog-picker')
    await page.setViewportSize({ width: 320, height: 568 })
    await snap('M18-catalog-picker-320')
    await page
      .getByRole('dialog')
      .getByRole('button', { name: '关闭', exact: true })
      .first()
      .click()
    await page.unroute('**/api/v1/settings/model-services/models')
  })
}
if (process.argv[2] === 'upload-limit') {
  await run('J03-upload-9-limit-duplicate-inflight', async () => {
    await page.goto(state.origin + '/assistant?new=1')
    await page.getByRole('textbox', { name: '工作消息' }).waitFor()
    let started
    const uploadStarted = new Promise((r) => {
      started = r
    })
    let release
    const pending = new Promise((r) => {
      release = r
    })
    await page.route('**/api/v1/uploads', async (route) => {
      if (route.request().method() === 'POST') {
        started()
        await pending
      }
      await route.continue()
    })
    const files = Array.from({ length: 9 }, (_, i) => ({
      name: `边界文件-${i + 1}.txt`,
      mimeType: 'text/plain',
      buffer: Buffer.from(`SPEC073_LIMIT_${i} isolated`),
    }))
    await page.locator('input[type=file]').nth(1).setInputFiles(files.slice(0, 4))
    await uploadStarted
    await page.getByRole('textbox', { name: '工作消息' }).fill('上传期间不可发送')
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
    await snap('J03-inflight-blocked', '真实上传请求暂缓用于观察空心圆；发送按钮禁用，未调用agent')
    release()
    await expect(page.getByLabel('上传中', { exact: true })).toHaveCount(0, { timeout: 15000 })
    await page.unroute('**/api/v1/uploads')
    await page.locator('input[type=file]').nth(1).setInputFiles(files.slice(4))
    await expect(page.getByLabel('上传中', { exact: true })).toHaveCount(0, { timeout: 15000 })
    await expect(
      page.getByRole('region', { name: '待发送附件，共 9 个，可横向滚动' }),
    ).toBeVisible()
    const before = requests.filter(
      (x) => x.method === 'POST' && x.path === '/api/v1/uploads',
    ).length
    await page
      .locator('input[type=file]')
      .nth(1)
      .setInputFiles({
        name: '超额文件.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from('十号文件'),
      })
    await expect(page.getByText(/最多.*9/)).toBeVisible()
    expect(requests.filter((x) => x.method === 'POST' && x.path === '/api/v1/uploads').length).toBe(
      before,
    )
    await snap('J03-over-limit', '4+5批次累计9个后，第10个被明确拒绝且没有额外上传请求')
    await page
      .getByRole('dialog', { name: '无法添加附件' })
      .getByRole('button', { name: '关闭', exact: true })
      .first()
      .click()
    const cards = page.getByRole('region', { name: '待发送附件，共 9 个，可横向滚动' })
    await cards.getByRole('button', { name: '移除边界文件-9.txt', exact: true }).click()
    await page.locator('input[type=file]').nth(1).setInputFiles(files[0])
    await expect(
      page.getByRole('region', { name: '待发送附件，共 9 个，可横向滚动' }),
    ).toBeVisible()
    await expect(page.getByLabel('上传中', { exact: true })).toHaveCount(0, { timeout: 15000 })
    await snap(
      'J03-identical-accepted',
      '同名同内容文件允许作为第9个附件；服务端按内容复用读取，不按文件名拒绝',
    )
    await page
      .getByRole('button', { name: /^移除边界文件-1/ })
      .last()
      .click()
    await page
      .locator('input[type=file]')
      .nth(1)
      .setInputFiles({ ...files[0], buffer: Buffer.from('不同正文同名文件') })
    await expect(
      page.getByRole('region', { name: '待发送附件，共 9 个，可横向滚动' }),
    ).toBeVisible()
    await expect(page.getByLabel('上传中', { exact: true })).toHaveCount(0, { timeout: 15000 })
    await snap('J03-same-name-distinct', '同名但不同内容作为独立文件接受')
    while (await page.getByRole('button', { name: /^移除边界文件/ }).count()) {
      await page
        .getByRole('button', { name: /^移除边界文件/ })
        .first()
        .click()
    }
    await expect(page.getByRole('region', { name: /待发送附件/ })).toHaveCount(0)
    await snap('J03-all-draft-files-removed', '本用例9个草稿附件均经UI删除')
  })
}
if (process.argv[2] === 'real-stream') {
  const cdp = await context.newCDPSession(page)
  await cdp.send('Network.enable')
  const events = []
  cdp.on('Network.eventSourceMessageReceived', (e) =>
    events.push({ event: e.eventName, length: e.data.length, at: Date.now() }),
  )
  await run('J05-real-stream-leave-return-complete-cancel-context', async () => {
    await page.goto(state.origin + '/assistant?new=1')
    await page
      .getByRole('textbox', { name: '工作消息' })
      .fill('SPEC073_MARKER_STREAM 请输出受控长回复，用于测试切换返回。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    const reply = page.getByText(/受控 UI 验收回复/).last()
    await expect(reply).toBeVisible({ timeout: 30000 })
    const samples = []
    for (let i = 0; i < 3; i++) {
      samples.push({ at: Date.now(), length: (await reply.textContent()).length })
      await page.waitForTimeout(450)
    }
    expect(samples.at(-1).length).toBeGreaterThan(samples[0].length)
    await expect(page.getByRole('button', { name: '中断', exact: true })).toBeVisible()
    await snap(
      'J05-real-stream-active',
      '生产API/worker/Redis/SSE链路；连续正文采样长度增长，模型回复为本地固定合成',
    )
    const url = page.url()
    await page.goto(state.origin + '/work')
    await expect(page.getByRole('heading', { name: '我的工作', exact: true })).toBeVisible()
    await page.goto(url)
    await expect(reply).toBeVisible()
    await expect(page.getByRole('button', { name: '中断', exact: true })).toBeVisible()
    await snap('J05-real-stream-return', '活动任务切至我的工作再返回，持续正文重新衔接')
    await expect(page.getByRole('button', { name: '中断', exact: true })).toHaveCount(0, {
      timeout: 60000,
    })
    await expect(reply).toContainText('第24段')
    await page.reload()
    await expect(reply).toContainText('第24段')
    await snap('J05-real-stream-complete-refresh', '完整流式任务完成后刷新，数据库正文完整存在')
    await page
      .getByRole('textbox', { name: '工作消息' })
      .fill('SPEC073_MARKER_STREAM_CANCEL 这条用于中断测试。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.getByText(/受控 UI 验收回复/)).toHaveCount(2, { timeout: 30000 })
    await page.waitForTimeout(700)
    await page.getByRole('button', { name: '中断', exact: true }).click()
    await expect(page.getByRole('button', { name: /^中断/ })).toHaveCount(0, { timeout: 15000 })
    await expect(page.getByText('已中断', { exact: true }).first()).toBeVisible()
    await snap('J05-real-cancelled', '真实中断请求和任务终态')
    await page.getByRole('button', { name: '更多功能', exact: true }).click()
    await page.getByRole('button', { name: /^上下文使用情况：/ }).click()
    await expect(page.getByRole('dialog', { name: '上下文使用情况', exact: true })).toBeVisible()
    await expect(page.getByText('上下文处理未完成', { exact: true })).toHaveCount(0)
    await snap('J05-real-cancel-context', '中断后上下文对话框不显示处理未完成')
    await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
    await page.reload()
    await expect(page.getByText('已中断', { exact: true }).first()).toBeVisible()
    await snap('J05-real-cancel-refresh', '中断后刷新终态保持')
    expect(events.filter((x) => x.event === 'reply_delta').length).toBeGreaterThan(3)
    expect(events.filter((x) => x.event === 'reply_unavailable')).toHaveLength(0)
    writeFileSync(
      resolve(output, 'J05-real-stream-proof.json'),
      JSON.stringify(
        { url, samples, events, controlledModel: true, realAPI: true, ownedRedis: true },
        null,
        2,
      ),
    )
  })
  writeFileSync(resolve(output, 'J05-event-observations.json'), JSON.stringify(events, null, 2))
}
if (process.argv[2] === 'stream-tail') {
  await run('J05-real-cancel-context-refresh-tail', async () => {
    const prior = JSON.parse(
      readFileSync(resolve(output, 'journeys-real-stream-results.json'), 'utf8'),
    )
    const url = prior.shots.at(-1).url
    await page.goto(url)
    await expect(page.getByRole('textbox', { name: '工作消息' })).toBeVisible()
    const latest = page.getByRole('button', { name: /回到最新/ })
    if (await latest.isVisible()) await latest.click()
    await expect(page.getByText('已中断', { exact: true }).first()).toBeVisible()
    await snap('J05-real-cancelled', '原真实任务已成功中断；原失败是误取折叠列表里的同名隐藏状态')
    await page.getByRole('button', { name: '更多功能', exact: true }).click()
    await page.getByRole('button', { name: /^上下文使用情况：/ }).click()
    await expect(page.getByRole('dialog', { name: '上下文使用情况', exact: true })).toBeVisible()
    await expect(page.getByText('上下文处理未完成', { exact: true })).toHaveCount(0)
    await snap('J05-real-cancel-context', '中断后上下文对话框无处理未完成，实际估算仍可读')
    await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
    await page.reload()
    await expect(page.getByText('已中断', { exact: true }).first()).toBeVisible()
    await snap('J05-real-cancel-refresh', '中断后刷新保持终态')
    const events = JSON.parse(readFileSync(resolve(output, 'J05-event-observations.json'), 'utf8'))
    expect(events.filter((x) => x.event === 'reply_delta').length).toBeGreaterThan(3)
    expect(events.filter((x) => x.event === 'reply_unavailable')).toHaveLength(0)
    writeFileSync(
      resolve(output, 'J05-real-stream-proof.json'),
      JSON.stringify(
        {
          url,
          events,
          controlledModel: true,
          realAPI: true,
          ownedRedis: true,
          partialTextGrowthAssertion: 'passed before original hidden-state locator failure',
          completeAndRefreshAssertion: '第24段 visible after reload',
          continuation: 'Cancelled status and context verified by stream-tail mode',
        },
        null,
        2,
      ),
    )
  })
}
if (process.argv[2] === 'stable-evidence') {
  await run('J08-J10-stable-final-views', async () => {
    await page.goto(state.origin + '/reports/' + fixtures.workflow)
    await expect(
      page.getByText('SPEC073 已完成手机布局检查，记录可复现证据。', { exact: true }),
    ).toBeVisible()
    await page.getByRole('link', { name: '返回我的报告', exact: true }).click()
    await page.waitForURL((url) => !url.pathname.includes(fixtures.workflow))
    await expect(page.getByRole('heading', { name: '我的报告', exact: true })).toBeVisible()
    await snap('J08-report-return-stable', '只读补拍返回我的报告的稳定状态；原立即截图为转场')
    const list = await api('/announcements?state=published&cursor=0')
    const announcement = list.data.items[0]
    expect(announcement).toBeTruthy()
    await page.goto(state.origin + '/notifications/announcements/' + announcement.id)
    await expect(page.getByRole('heading', { name: announcement.title, exact: true })).toBeVisible()
    await snap(
      'J10-announcement-user-detail-stable',
      '读取现存合成公告详情；J10原新增公告已按真实流程删除',
    )
    await context.clearCookies()
    await login('admin')
    await page.goto(state.origin + '/announcement-management/' + announcement.id)
    await expect(page.getByRole('heading', { name: announcement.title, exact: true })).toBeVisible()
    await snap(
      'J10-announcement-admin-detail-stable',
      '现存合成公告管理详情稳定态，不将转场当作最终页面',
    )
    await page.goto(state.origin + '/announcement-management')
    await expect(page.getByRole('heading', { name: '公告管理', exact: true })).toBeVisible()
    await expect(
      page.getByRole('link', { name: /SPEC073 真实公告发布与删除连续旅程/ }),
    ).toHaveCount(0)
    await snap('J10-announcement-deleted-stable', '原J10公告已删除，稳定管理列表不再出现该记录')
  })
}
if (process.argv[2] === 'model-360') {
  await run('M18-360-routing-and-dialog', async () => {
    await page.setViewportSize({ width: 360, height: 780 })
    await page.goto(state.origin + '/settings/models')
    await page.getByRole('tab', { name: '用途分配', exact: true }).click()
    await expect(page.getByRole('button', { name: '保存用途分配', exact: true })).toBeVisible()
    await snap('M18-routing-360', '补360宽度代表用途页，只读')
    await page.getByRole('tab', { name: '服务配置', exact: true }).click()
    await page
      .getByRole('button', {
        name: '设置 synthetic-model-long-name-for-mobile-ui-review',
        exact: true,
      })
      .click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await snap('M18-model-options-360', '补360宽度代表长模型名和思考档位弹层，只读')
  })
}
if (process.argv[2] === 'model-theme') {
  await run('M18-stable-dark-and-expanded-controls', async () => {
    await page.goto(state.origin + '/settings/models')
    await page.getByRole('tab', { name: '用途分配', exact: true }).click()
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark')
    await page.waitForTimeout(220)
    const colors = await page
      .getByRole('button', { name: '展开导航', exact: true })
      .evaluate((n) => ({
        color: getComputedStyle(n).color,
        svg: getComputedStyle(n.querySelector('svg')).color,
        body: getComputedStyle(document.body).color,
        background: getComputedStyle(n.closest('section')).backgroundColor,
      }))
    writeFileSync(resolve(output, 'M18-dark-colors.json'), JSON.stringify(colors, null, 2))
    await snap('M18-routing-dark-stable', '系统主题切换完成后220ms；检查实际计算颜色')
    await page.getByText('语音转写', { exact: true }).click()
    await page.getByText('图片生成', { exact: true }).click()
    await snap('M18-routing-all-expanded-dark')
    await page.setViewportSize({ width: 320, height: 568 })
    await page.getByRole('button', { name: '保存用途分配', exact: true }).scrollIntoViewIfNeeded()
    await snap('M18-routing-expanded-bottom-320')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ colorScheme: 'light' })
    await page.waitForTimeout(220)
    await page.getByRole('tab', { name: '服务配置', exact: true }).click()
    await page
      .getByRole('button', {
        name: '设置 synthetic-model-long-name-for-mobile-ui-review',
        exact: true,
      })
      .click()
    await page.setViewportSize({ width: 320, height: 568 })
    const modal = page.getByRole('dialog')
    await modal.getByText('高级请求参数', { exact: true }).click()
    await modal.getByRole('button', { name: '完成', exact: true }).scrollIntoViewIfNeeded()
    await snap('M18-advanced-parameters-320')
    const geometry = await page.locator('dialog input, dialog button').evaluateAll((ns) =>
      ns.map((n) => {
        const r = n.getBoundingClientRect()
        return {
          name: n.getAttribute('aria-label') || n.textContent,
          width: r.width,
          height: r.height,
          x: r.x,
          y: r.y,
        }
      }),
    )
    writeFileSync(resolve(output, 'M18-control-geometry.json'), JSON.stringify(geometry, null, 2))
  })
}
save()
console.log(JSON.stringify({ results, shots: shots.length, errors }, null, 2))
await browser.close()
