// Real UI journeys, with independent API readback and unmodified provider responses.
import { chromium } from 'playwright'
import { readFileSync, writeFileSync, appendFileSync, mkdirSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { api, browserEnvironment } from './agent-browser-common.mjs'
import { runInteractive } from './agent-browser-interactive.mjs'

if (process.argv.includes('--help')) {
  console.log(`Batch: SPEC054_ENVIRONMENT, SPEC054_AGENT_OUTPUT, SPEC054_CASES; optional SPEC054_CASE_IDS.
Legacy interactive: SPEC044_STATE; optional SPEC044_AGENT_OUTPUT. Send JSON commands on stdin:
open, send, wait, view, click, fill, fields, upload, goto, read, offline, close.
Both modes require credentials linked to an owned local acceptance manifest.`)
} else if (process.env.SPEC044_STATE && !process.env.SPEC054_ENVIRONMENT) {
  await runInteractive()
} else {
  const metadataPath = process.env.SPEC054_ENVIRONMENT
  const output = process.env.SPEC054_AGENT_OUTPUT
  const casesPath = process.env.SPEC054_CASES
  if (!metadataPath || !output || !casesPath)
    throw new Error('Environment, frozen cases and output are required')
  const { metadata, state } = browserEnvironment({ metadataPath })
  mkdirSync(output, { recursive: true })
  const run = {
    caseSha256: createHash('sha256').update(readFileSync(casesPath)).digest('hex'),
    runId: metadata.runId,
    channel: 'browser',
    requestLimit: null,
  }
  if (existsSync(`${output}/run.json`))
    throw new Error('Refusing to overwrite browser first results')
  writeFileSync(`${output}/run.json`, JSON.stringify(run, null, 2))
  const cases = JSON.parse(readFileSync(casesPath, 'utf8')).filter(
    (item) =>
      item.channel === 'browser' &&
      (!process.env.SPEC054_CASE_IDS || process.env.SPEC054_CASE_IDS.split(',').includes(item.id)),
  )
  const browser = await chromium.launch()
  const terminal = new Set(['succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'])

  async function records(page) {
    const result = {}
    for (const [name, path] of [
      ['work', '/api/v1/work-items'],
      ['daily', '/api/v1/reports?kind=daily'],
      ['weekly', '/api/v1/reports?kind=weekly'],
    ]) {
      const items = []
      let cursor = null
      const seen = new Set()
      try {
        do {
          const data = await api(
            page,
            path +
              (path.includes('?') ? '&' : '?') +
              'limit=20' +
              (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''),
          )
          items.push(...(data.items ?? []))
          cursor = data.nextCursor
          if (cursor && seen.has(cursor)) throw new Error('Cursor repeated')
          seen.add(cursor)
        } while (cursor)
        result[name] = items
      } catch (error) {
        result[name] = { error: error.message }
      }
    }
    return result
  }
  async function journey(item) {
    const directory = `${output}/${item.id}`
    mkdirSync(directory, { recursive: true })
    const role = item.role === 'realAdmin' ? 'admin' : 'employee'
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      reducedMotion: 'no-preference',
      recordVideo: { dir: `${directory}/video`, size: { width: 960, height: 667 } },
    })
    const page = await context.newPage()
    page.setDefaultTimeout(15000)
    const consoleErrors = []
    page.on('pageerror', (error) => consoleErrors.push(error.message))
    const rows = []
    let before, previousEffort, reasoning
    try {
      await page.goto(state.origin)
      await page.getByRole('button', { name: /直接登录/ }).click()
      await page.getByLabel('账号', { exact: true }).fill(state.users[role].username)
      await page.getByLabel('密码', { exact: true }).fill(state.users[role].password)
      await page.getByRole('button', { name: '登录', exact: true }).click()
      await page
        .getByRole('navigation', { name: '工作空间', includeHidden: true })
        .waitFor({ state: 'attached' })
      const mode = await api(page, '/api/v1/assistant/execution-settings')
      if (mode.executionMode !== item.mode)
        await api(page, '/api/v1/assistant/execution-settings', 'PATCH', {
          executionMode: item.mode,
          fullAccessConfirmed: true,
          expectedRevision: mode.modeRevision,
        })
      if (item.effort) {
        reasoning = await api(page, '/api/v1/assistant/reasoning-settings')
        previousEffort = reasoning.selected?.effort
        reasoning = await api(page, '/api/v1/assistant/reasoning-settings', 'PATCH', {
          effort: item.effort,
          preferenceRevision: reasoning.preferenceRevision,
          configVersion: reasoning.configVersion,
        })
      }
      await page.getByRole('link', { name: '聊天搭子', exact: true }).click()
      await page.getByRole('button', { name: '新会话', exact: true }).click()
      await page.getByRole('button', { name: /选择人设：/ }).click()
      await page
        .getByRole('menuitemradio', { name: item.persona === 'dabao' ? /Noria人设/ : /专业人设/ })
        .click()
      before = await records(page)
      for (const [index, prompt] of item.turns.entries()) {
        const began = Date.now()
        const row = {
          case: item.id,
          turn: index + 1,
          prompt,
          samples: [],
          classification: 'review-required',
        }
        try {
          const editor = page.getByRole('textbox', { name: '工作消息' })
          await editor.fill(prompt)
          const accepted = page.waitForResponse(
            (response) =>
              response.request().method() === 'POST' &&
              new URL(response.url()).pathname === '/api/v1/messages',
          )
          await page.getByRole('button', { name: '发送', exact: true }).click()
          const response = await accepted
          if (response.status() !== 202) throw new Error(`Send HTTP ${response.status()}`)
          const receipt = await response.json()
          row.receipt = receipt
          if (item.cancelFirst && index === 0)
            await page.getByRole('button', { name: '中断', exact: true }).click()
          let previous = ''
          while (Date.now() - began < 300000) {
            const live = await page.locator('[data-reply-state]').allTextContents()
            const text = live.at(-1) ?? ''
            if (text && text !== previous) {
              row.samples.push({ ms: Date.now() - began, text })
              previous = text
            }
            row.message = await api(page, '/api/v1/messages/' + receipt.messageId)
            if (terminal.has(row.message.job?.state)) break
            await page.waitForTimeout(350)
          }
          if (!terminal.has(row.message?.job?.state))
            throw new Error('Real journey exceeded per-turn timeout')
          // Allow the already received final text to finish its visual reveal.
          await page
            .getByRole('button', { name: '发送', exact: true })
            .waitFor({ state: 'visible', timeout: 30000 })
          row.readback = await records(page)
          row.ui = await page.locator('[data-chat-content]').innerText()
          row.seconds = (Date.now() - began) / 1000
          await page.screenshot({ path: `${directory}/turn-${index + 1}.png`, fullPage: true })
        } catch (error) {
          row.exception = error.message
          row.classification = 'incomplete'
          if (row.receipt) {
            const job = await api(page, '/api/v1/jobs/' + row.receipt.jobId).catch(() => null)
            if (job && ['queued', 'running'].includes(job.state))
              await api(page, '/api/v1/jobs/' + job.id + '/cancel', 'POST', {
                expectedAttempt: job.attempt,
                expectedFence: job.fence,
              }).catch(() => {})
          }
        }
        rows.push(row)
        appendFileSync(`${directory}/first.jsonl`, JSON.stringify(row) + '\n')
        console.log(
          JSON.stringify({
            case: item.id,
            turn: index + 1,
            state: row.message?.job?.state,
            samples: row.samples.length,
            error: row.exception,
            seconds: row.seconds,
          }),
        )
        if (row.exception || ['failed', 'awaiting_retry'].includes(row.message?.job?.state)) break
      }
      writeFileSync(
        `${directory}/result.json`,
        JSON.stringify(
          {
            case: item,
            before,
            reasoning,
            turns: rows,
            after: await records(page),
            consoleErrors,
            classification: 'review-required',
          },
          null,
          2,
        ),
      )
    } catch (error) {
      writeFileSync(
        `${directory}/setup-failure.json`,
        JSON.stringify({ case: item.id, error: error.message, consoleErrors }, null, 2),
      )
      console.log(JSON.stringify({ case: item.id, setupError: error.message }))
      await page.screenshot({ path: `${directory}/setup-failure.png` }).catch(() => {})
    } finally {
      if (previousEffort) {
        const current = await api(page, '/api/v1/assistant/reasoning-settings')
        await api(page, '/api/v1/assistant/reasoning-settings', 'PATCH', {
          effort: previousEffort,
          preferenceRevision: current.preferenceRevision,
          configVersion: current.configVersion,
        })
      }
      await context.close()
    }
  }
  try {
    await Promise.all(
      ['realAdmin', 'realEmployee'].map(async (role) => {
        for (const item of cases.filter((entry) => entry.role === role)) await journey(item)
      }),
    )
  } finally {
    await browser.close()
  }
}
