// Formal Web only. Adaptive commands are append-only evidence, never a mock server.
import { chromium } from 'playwright'
import { createInterface } from 'node:readline'
import {
  mkdirSync,
  writeFileSync,
  appendFileSync,
  readFileSync,
  existsSync,
  readdirSync,
} from 'node:fs'
import { createHash } from 'node:crypto'
import { api, browserEnvironment } from '../agent-browser-common.mjs'
const { metadata, state } = browserEnvironment({ metadataPath: process.env.SPEC080_ENVIRONMENT })
if (metadata.suite !== 'spec080') throw new Error('Spec080 environment required')
const root = process.env.SPEC080_OUTPUT
if (!root || existsSync(`${root}/journal.jsonl`)) throw new Error('Unique evidence output required')
mkdirSync(root, { recursive: true })
const cases = JSON.parse(readFileSync(new URL('./cases.json', import.meta.url)))
if (process.env.SPEC080_SUPPLEMENTAL_CASES)
  cases.ai.push(...JSON.parse(readFileSync(process.env.SPEC080_SUPPLEMENTAL_CASES)).ai)
const browser = await chromium.launch()
let context,
  page,
  lastReceipt,
  index = 0,
  contextSerial = 0
const save = (name, value) =>
  writeFileSync(`${root}/${name}.json`, JSON.stringify(value, null, 2), { flag: 'wx' })
async function snapshot() {
  await page.screenshot({ path: `${root}/${index}.png`, fullPage: true })
  return {
    contextSerial,
    url: page.url(),
    text: await page.locator('body').innerText(),
    buttons: await page.getByRole('button').allTextContents(),
    buttonLabels: await page.getByRole('button').evaluateAll((ns) =>
      ns.map((n) => ({
        text: n.innerText,
        label: n.getAttribute('aria-label'),
        title: n.getAttribute('title'),
      })),
    ),
    fields: await page
      .locator('input:not([type=password]), textarea, select')
      .evaluateAll((nodes) =>
        nodes.map((n) => ({
          tag: n.tagName,
          type: n.type,
          placeholder: n.placeholder,
          label: [...(n.labels ?? [])].map((l) => l.innerText),
          value: n.value,
        })),
      ),
    links: await page
      .getByRole('link')
      .evaluateAll((nodes) =>
        nodes.map((n) => ({ text: n.innerText, href: n.getAttribute('href') })),
      ),
    overflow: await page.evaluate(() => ({
      viewport: innerWidth,
      document: document.documentElement.scrollWidth,
    })),
  }
}
async function waitMessage() {
  if (!lastReceipt) throw new Error('No accepted message')
  const started = Date.now(),
    samples = []
  while (Date.now() - started < 600000) {
    const message = await api(page, '/api/v1/messages/' + lastReceipt.messageId)
    samples.push({
      time: Date.now(),
      state: message.job?.state,
      phase: message.job?.phase,
      reply: message.reply?.length,
    })
    if (
      ['succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'].includes(
        message.job?.state,
      )
    )
      return { message, samples, ui: await snapshot() }
    await page.waitForTimeout(1000)
  }
  return { timeout: true, receipt: lastReceipt, samples, ui: await snapshot() }
}
async function open(c) {
  if (context) await context.close()
  contextSerial++
  context = await browser.newContext({
    viewport: { width: c.width ?? 1280, height: 960 },
    isMobile: !!c.mobile,
    hasTouch: !!c.mobile,
    reducedMotion: 'reduce',
    acceptDownloads: true,
  })
  page = await context.newPage()
  page.setDefaultTimeout(12000)
  page.on('response', async (r) => {
    const url = new URL(r.url())
    if (!url.pathname.startsWith('/api/v1/') || url.pathname.startsWith('/api/v1/auth/')) return
    const row = {
      time: Date.now(),
      method: r.request().method(),
      path: url.pathname + url.search,
      status: r.status(),
    }
    if (row.method !== 'GET') {
      row.body = r.request().postData()
      row.response = await r.json().catch(() => null)
    }
    appendFileSync(`${root}/network.jsonl`, JSON.stringify(row) + '\n')
    if (row.method === 'POST' && url.pathname === '/api/v1/messages' && r.status() === 202) {
      lastReceipt = row.response
    }
  })
  page.on('pageerror', (error) =>
    appendFileSync(
      `${root}/console.jsonl`,
      JSON.stringify({ time: Date.now(), error: error.message }) + '\n',
    ),
  )
  await page.goto(state.origin)
  return login(c)
}
async function login(c) {
  if (await page.getByRole('button', { name: /直接登录/ }).isVisible())
    await page.getByRole('button', { name: /直接登录/ }).click()
  const user = state.users[c.user ?? 'employee']
  if (!user) throw new Error('Unknown synthetic role')
  await page.getByLabel('账号', { exact: true }).fill(user.username)
  await page.getByLabel('密码', { exact: true }).fill(user.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page
    .getByRole('navigation', { name: '工作空间', includeHidden: true })
    .waitFor({ state: 'attached' })
  lastReceipt = null
  return snapshot()
}
function target(c) {
  if (c.selector) return page.locator(c.selector).nth(c.nth ?? 0)
  if (c.label) return page.getByLabel(c.label, { exact: !c.partial }).nth(c.nth ?? 0)
  if (c.text) return page.getByText(c.text, { exact: !c.partial }).nth(c.nth ?? 0)
  return page
    .getByRole(c.role ?? 'button', { name: c.regex ? new RegExp(c.name) : c.name, exact: !c.regex })
    .nth(c.nth ?? 0)
}
async function execute(c) {
  if (c.op === 'open') return open(c)
  if (c.op === 'login') return login(c)
  if (c.op === 'view') return snapshot()
  if (c.op === 'goto') {
    if (!c.path.startsWith('/') || c.path.startsWith('//')) throw new Error('local only')
    await page.goto(state.origin + c.path)
    return snapshot()
  }
  if (c.op === 'reload') {
    await page.reload()
    return snapshot()
  }
  if (c.op === 'click') {
    if (c.acceptDialog) page.once('dialog', (d) => d.accept())
    await target(c).click()
    await page.waitForTimeout(400)
    return snapshot()
  }
  if (c.op === 'fill') {
    await target(c).fill(c.value)
    return snapshot()
  }
  if (c.op === 'select') {
    await target(c).selectOption(c.value)
    return snapshot()
  }
  if (c.op === 'press') {
    await target(c).press(c.key)
    return snapshot()
  }
  if (c.op === 'audit')
    return page.locator(c.selector).evaluateAll((ns) =>
      ns.map((n) => {
        const s = getComputedStyle(n),
          r = n.getBoundingClientRect()
        return {
          text: n.innerText,
          role: n.getAttribute('role'),
          href: n.getAttribute('href'),
          rect: { x: r.x, y: r.y, width: r.width, height: r.height },
          whiteSpace: s.whiteSpace,
          overflow: s.overflow,
          textOverflow: s.textOverflow,
        }
      }),
    )
  if (c.op === 'hover') {
    await target(c).hover()
    return snapshot()
  }
  if (c.op === 'check') {
    await target(c).setChecked(c.checked ?? true)
    return snapshot()
  }
  if (c.op === 'upload') {
    await page
      .locator('input[type=file]')
      .nth(c.nth ?? 1)
      .setInputFiles(c.paths)
    return snapshot()
  }
  if (c.op === 'read') return api(page, c.path)
  if (c.op === 'offline') {
    await context.setOffline(c.value)
    return snapshot()
  }
  if (c.op === 'viewport') {
    await page.setViewportSize({ width: c.width, height: c.height ?? 900 })
    return snapshot()
  }
  if (c.op === 'download') {
    const download = page.waitForEvent('download')
    void download.catch(() => {})
    await target(c).click()
    const file = await download
    const path = `${root}/${index}-${file.suggestedFilename()}`
    await file.saveAs(path)
    const bytes = readFileSync(path)
    return {
      filename: file.suggestedFilename(),
      bytes: bytes.length,
      sha256: createHash('sha256').update(bytes).digest('hex'),
      ui: await snapshot(),
    }
  }
  if (c.op === 'settings') {
    if (c.mode) {
      await page.getByRole('button', { name: /^执行权限：/ }).click()
      await page
        .getByRole('menuitemradio', {
          name: new RegExp('^' + { full: '自主执行', ask: '逐项确认', auto: '自动审核' }[c.mode]),
        })
        .click()
      const dialog = page.getByRole('dialog', { name: '开启自主执行' })
      if (await dialog.isVisible())
        await dialog.getByRole('button', { name: '开启自主执行', exact: true }).click()
    }
    if (c.effort) {
      const r = await api(page, '/api/v1/assistant/reasoning-settings')
      if (!r.options.some((o) => o.effort === c.effort)) throw new Error('Effort unavailable')
      if (r.selected?.effort !== c.effort) {
        await page.getByRole('button', { name: /^思考强度：/ }).click()
        await page.getByRole('menuitemradio', { name: c.effort, exact: true }).click()
      }
    }
    return {
      reasoning: await api(page, '/api/v1/assistant/reasoning-settings'),
      execution: await api(page, '/api/v1/assistant/execution-settings'),
      ui: await snapshot(),
    }
  }
  if (c.op === 'send') {
    const item = cases.ai.find((x) => x.id === c.case)
    if (!item) throw new Error('Frozen scenario required')
    const key = `${c.case}-${c.effort}-attempt-1`
    const ledgerRoot = 'artifacts/recent-changes-regression/cases'
    if (
      readdirSync(ledgerRoot, { withFileTypes: true }).some(
        (d) => d.isDirectory() && existsSync(`${ledgerRoot}/${d.name}/${key}.json`),
      )
    )
      throw new Error('First attempt already exists in this run')
    const effective = await api(page, '/api/v1/assistant/reasoning-settings')
    if (effective.selected?.effort !== c.effort)
      throw new Error('Actual effort differs from frozen attempt')
    const prompt = item.prompt
      .replaceAll('{{run}}', metadata.runId.slice(0, 8))
      .replaceAll('{{effort}}', c.effort)
    save(key, {
      started: Date.now(),
      prompt,
      caseSha256: createHash('sha256').update(JSON.stringify(item)).digest('hex'),
      effort: c.effort,
    })
    const globalReceipts = readdirSync(ledgerRoot, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .flatMap((d) => {
        const path = `${ledgerRoot}/${d.name}/network.jsonl`
        return existsSync(path)
          ? readFileSync(path, 'utf8')
              .trim()
              .split('\n')
              .filter(Boolean)
              .map((l) => JSON.parse(l))
          : []
      })
      .filter((r) => r.method === 'POST' && r.path === '/api/v1/messages' && r.status === 202)
    if (globalReceipts.length >= cases.budget.maxMessages)
      throw new Error('Global frozen request budget reached')
    const accepted = page.waitForResponse(
      (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/v1/messages',
    )
    await page.getByRole('textbox', { name: '工作消息' }).fill(prompt)
    await page.getByRole('button', { name: '发送', exact: true }).click()
    const response = await accepted
    lastReceipt = await response.json()
    save(`${key}-accepted`, { status: response.status(), receipt: lastReceipt, time: Date.now() })
    if (response.status() !== 202) throw new Error(`Admission ${response.status()}`)
    if (c.noWait) return { receipt: lastReceipt, ui: await snapshot() }
    const result = await waitMessage()
    save(`${key}-result`, result)
    return result
  }
  if (c.op === 'wait') return waitMessage()
  if (c.op === 'close') return { closed: true }
  throw new Error('Unknown command')
}
try {
  for await (const line of createInterface({ input: process.stdin })) {
    if (!line.trim()) continue
    const c = JSON.parse(line)
    index++
    const start = Date.now()
    let row
    try {
      row = { index, command: c, started: start, finished: Date.now(), result: await execute(c) }
    } catch (error) {
      row = { index, command: c, started: start, error: error.message }
      if (page) row.ui = await snapshot().catch(() => null)
    }
    row.finished = Date.now()
    appendFileSync(`${root}/journal.jsonl`, JSON.stringify(row) + '\n')
    console.log(JSON.stringify(row))
    if (c.op === 'close') break
  }
} finally {
  await browser.close()
}
