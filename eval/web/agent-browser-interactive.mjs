// Original line-delimited browser protocol for adaptive synthetic user journeys.
import { chromium } from 'playwright'
import { writeFileSync, appendFileSync, mkdirSync } from 'node:fs'
import { createInterface } from 'node:readline'
import { api, browserEnvironment } from './agent-browser-common.mjs'

export async function runInteractive() {
  const { state } = browserEnvironment({ statePath: process.env.SPEC044_STATE })
  const output = process.env.SPEC044_AGENT_OUTPUT || 'artifacts/spec044/agent/browser'
  mkdirSync(output, { recursive: true })
  const browser = await chromium.launch()
  let context,
    page,
    scenario,
    index = 0,
    accepted = []
  async function snapshot() {
    const text = await page.locator('body').innerText()
    const buttons = await page.getByRole('button').allTextContents()
    await page.screenshot({ path: `${output}/${scenario}-${index}.png` })
    return { url: page.url(), text, buttons }
  }
  async function latest() {
    if (!accepted.length) return null
    return api(page, '/api/v1/messages/' + accepted.at(-1).messageId)
  }
  async function wait() {
    await page
      .getByRole('button', { name: '中断', exact: true })
      .waitFor({ state: 'hidden', timeout: 240_000 })
    await page
      .getByRole('button', { name: '正在发送', exact: true })
      .waitFor({ state: 'hidden', timeout: 10_000 })
    return { ui: await snapshot(), message: await latest() }
  }
  async function execute(command) {
    index++
    if (command.op === 'open') {
      if (context) await context.close()
      scenario = command.id
      if (!/^[A-Z][A-Z0-9_-]+$/.test(scenario)) throw new Error('Invalid case ID')
      context = await browser.newContext({
        viewport: { width: 1440, height: 1000 },
        reducedMotion: 'reduce',
      })
      page = await context.newPage()
      page.setDefaultTimeout(12_000)
      accepted = []
      page.on('response', async (response) => {
        if (
          response.request().method() === 'POST' &&
          new URL(response.url()).pathname === '/api/v1/messages' &&
          response.status() === 202
        ) {
          const receipt = await response.json().catch(() => null)
          if (receipt) accepted.push(receipt)
        }
      })
      await page.goto(state.origin)
      await page.getByRole('button', { name: /直接登录/ }).click()
      const user = state.users[command.role ?? 'realEmployee']
      if (!user) throw new Error('Unknown synthetic test account')
      await page.getByLabel('账号', { exact: true }).fill(user.username)
      await page.getByLabel('密码', { exact: true }).fill(user.password)
      await page.getByRole('button', { name: '登录', exact: true }).click()
      await page
        .getByRole('navigation', { name: '工作空间', includeHidden: true })
        .waitFor({ state: 'attached' })
      await page.getByRole('button', { name: '新会话', exact: true }).click()
      return snapshot()
    }
    if (command.op === 'send') {
      const editor = page.getByRole('textbox', { name: '工作消息' })
      await editor.fill(command.text)
      const response = page.waitForResponse(
        (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/v1/messages',
      )
      await editor.press('Enter')
      const sent = await response
      if (sent.status() !== 202) return { sentStatus: sent.status(), ui: await snapshot() }
      await page
        .getByRole('button', { name: '中断', exact: true })
        .waitFor({ timeout: 3000 })
        .catch(() => {})
      if (command.noWait) return snapshot()
      return wait()
    }
    if (command.op === 'wait') return wait()
    if (command.op === 'view') return snapshot()
    if (command.op === 'click') {
      await page
        .getByRole(command.role ?? 'button', {
          name: command.regex ? new RegExp(command.name) : command.name,
          exact: !command.regex,
        })
        .nth(command.nth ?? 0)
        .click()
      return snapshot()
    }
    if (command.op === 'fill') {
      await page.getByLabel(command.label, { exact: command.exact ?? true }).fill(command.text)
      return snapshot()
    }
    if (command.op === 'fields') {
      return page.locator('input, textarea').evaluateAll((fields) =>
        fields
          .filter((field) => field.type !== 'password')
          .map((field) => ({
            tag: field.tagName,
            name: field.name,
            label: Array.from(field.labels ?? []).map((label) => label.innerText),
            value: field.value,
          })),
      )
    }
    if (command.op === 'upload') {
      await page
        .locator('input[type=file]')
        .nth(command.image ? 0 : 1)
        .setInputFiles(command.path)
      return snapshot()
    }
    if (command.op === 'goto') {
      if (!command.path.startsWith('/') || command.path.startsWith('//'))
        throw new Error('local only')
      await page.goto(state.origin + command.path)
      return snapshot()
    }
    if (command.op === 'read') {
      if (!command.path.startsWith('/api/v1/')) throw new Error('local API only')
      return page.evaluate(async (path) => (await fetch(path)).json(), command.path)
    }
    if (command.op === 'offline') {
      await context.setOffline(command.value)
      return snapshot()
    }
    if (command.op === 'close') return { closed: true }
    throw new Error('Unknown operation')
  }
  try {
    for await (const line of createInterface({ input: process.stdin })) {
      if (!line.trim()) continue
      const command = JSON.parse(line)
      const started = Date.now()
      try {
        const result = await execute(command)
        const entry = { command, seconds: (Date.now() - started) / 1000, result }
        appendFileSync(`${output}/journeys.jsonl`, JSON.stringify(entry) + '\n')
        writeFileSync(`${output}/latest.json`, JSON.stringify(entry, null, 2))
        console.log(JSON.stringify(entry))
      } catch (error) {
        const entry = { command, error: error.message }
        appendFileSync(`${output}/journeys.jsonl`, JSON.stringify(entry) + '\n')
        console.log(JSON.stringify(entry))
      }
      if (command.op === 'close') break
    }
  } finally {
    await browser.close()
  }
}
