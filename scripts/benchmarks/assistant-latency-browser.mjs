/** Real browser timing against an ownership-checked disposable API. No resends. */
import { chromium } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)))
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'])
const json = (path, value) => writeFileSync(path, JSON.stringify(value, null, 2) + '\n')
const append = (path, value) => appendFileSync(path, JSON.stringify(value) + '\n')

export async function stopBrowserObservation(page, row) {
  await page
    .evaluate(() => {
      if (window.__perf) window.__perf.stop = true
    })
    .catch((error) => {
      row.observerCleanupError = error.message
    })
}

export async function runBrowserJourney(options) {
  const metadataPath = resolve(options.metadata)
  execFileSync(
    resolve(root, '.venv-server/bin/python'),
    [
      '-c',
      "import sys;sys.path.insert(0,'scripts/company/web-acceptance');from environment import load_environment;load_environment(sys.argv[1])",
      metadataPath,
    ],
    { cwd: root, stdio: 'pipe' },
  )
  const metadata = JSON.parse(readFileSync(metadataPath, 'utf8'))
  if (metadata.suite !== 'spec056') throw new Error('Only an owned spec056 environment is allowed')
  const secret = JSON.parse(readFileSync(metadata.secretFile, 'utf8'))
  const manifest = JSON.parse(readFileSync(options.cases, 'utf8'))
  const journey = manifest.journeys.find((item) => item.id === options.journey)
  if (!journey || !journey.efforts.includes(options.effort))
    throw new Error('Unknown frozen journey/effort')
  const output = resolve(options.output)
  mkdirSync(output, { recursive: true })
  if (
    existsSync(resolve(output, 'admissions.jsonl')) ||
    existsSync(resolve(output, 'results.jsonl'))
  )
    throw new Error('Refusing to overwrite or resend first samples')
  const actor = secret.accounts[options.actor]
  if (!actor) throw new Error('Unknown synthetic actor')
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'no-preference',
  })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  let csrf
  const api = async (path, method = 'GET', body) => {
    const response = await context.request.fetch(metadata.origin + '/api/v1' + path, {
      method,
      headers: {
        Origin: metadata.origin,
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
        'Idempotency-Key': crypto.randomUUID(),
      },
      ...(body === undefined ? {} : { data: body }),
      timeout: 30_000,
    })
    if (!response.ok()) throw new Error(`${method} ${path}: HTTP ${response.status()}`)
    return response.json()
  }
  const rows = []
  try {
    const identity = await api('/auth/login', 'POST', {
      username: actor.username,
      password: actor.password,
    })
    csrf = identity.csrf
    const selection = await api('/assistant/reasoning-settings')
    if (selection.selected?.effort !== options.effort)
      throw new Error('Actual effort differs from frozen stratum')
    const mode = await api('/assistant/execution-settings')
    if (mode.executionMode !== journey.executionMode)
      await api('/assistant/execution-settings', 'PATCH', {
        executionMode: journey.executionMode,
        fullAccessConfirmed: true,
        expectedRevision: mode.modeRevision,
      })
    json(resolve(output, 'session.json'), {
      suite: metadata.suite,
      runId: metadata.runId,
      sourceCommit: metadata.commit,
      source: metadata.source,
      browserObserverSha256: createHash('sha256')
        .update(readFileSync(fileURLToPath(import.meta.url)))
        .digest('hex'),
      actor: actor.id,
      journey: journey.id,
      effort: options.effort,
      selection,
      casesSha256: createHash('sha256').update(readFileSync(options.cases)).digest('hex'),
      timingDefinition:
        'send click capture to first/complete DOM after two animation frames; report child jobs and downloadable files tracked separately',
    })
    const fixture = metadata.performanceFixtures?.[options.actor] ?? {}
    await page.goto(
      metadata.origin +
        (fixture.conversationId
          ? '/assistant/' + fixture.conversationId
          : '/assistant' + (journey.workReference ? '?workId=' + fixture.workId : '')),
    )
    await page.getByRole('textbox', { name: '工作消息', exact: true }).waitFor()
    const currentPersona = page.getByRole('button', { name: '选择人设：Noria人设', exact: true })
    if (journey.personaId === 'professional' && (await currentPersona.count())) {
      await currentPersona.click()
      await page.getByRole('menuitemradio', { name: /专业人设/ }).click()
      await page.getByRole('button', { name: '选择人设：专业人设', exact: true }).waitFor()
    }
    for (const [index, turn] of journey.turns.entries()) {
      const directory = resolve(output, `${index + 1}-${turn.id}`)
      mkdirSync(directory)
      const beforeWorks = await api('/work-items?limit=20')
      if (turn.attachment || (journey.fixture === 'attachment' && index === 0)) {
        const files = manifest.fixtures.attachment.map(({ name, mimeType, content }) => ({
          name,
          mimeType,
          buffer: Buffer.from(content),
        }))
        await page.locator('input[type=file]').first().setInputFiles(files)
      }
      const input = page.getByRole('textbox', { name: '工作消息', exact: true })
      await input.fill(turn.prompt)
      await page.evaluate(() => {
        window.__perf = {
          start: null,
          firstPaintMs: null,
          completePaintMs: null,
          previous: document.querySelectorAll('article[class*="_message_"]').length,
          terminal: false,
        }
        const button = [...document.querySelectorAll('button')].find(
          (item) => item.getAttribute('aria-label') === '发送' || item.title === '发送',
        )
        const begin = () => {
          if (window.__perf.start !== null) return
          window.__perf.start = performance.now()
          window.__perf.startUnixMs = Date.now()
          const tick = () => {
            const state = window.__perf
            const articles = document.querySelectorAll('article[class*="_message_"]')
            const last = articles.length > state.previous ? articles[articles.length - 1] : null
            const reply = last?.querySelector('div[class*="_reply_"]')
            if (reply?.textContent?.trim() && state.firstPaintMs === null)
              requestAnimationFrame(() => {
                if (state.firstPaintMs === null)
                  state.firstPaintMs = performance.now() - state.start
              })
            if (
              reply?.textContent?.trim() &&
              !reply.hasAttribute('data-reply-state') &&
              state.completePaintMs === null
            )
              requestAnimationFrame(() => {
                if (state.completePaintMs === null)
                  state.completePaintMs = performance.now() - state.start
              })
            if (!state.stop) requestAnimationFrame(tick)
          }
          requestAnimationFrame(tick)
        }
        if (button) button.addEventListener('click', begin, { once: true, capture: true })
        else document.addEventListener('click', begin, { once: true, capture: true })
      })
      const admission = page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          new URL(response.url()).pathname === '/api/v1/messages',
        { timeout: 30_000 },
      )
      const began = performance.now()
      await page.getByRole('button', { name: '发送', exact: true }).click()
      const response = await admission
      const receipt = await response.json()
      if (response.status() !== 202) throw new Error(`Message admission HTTP ${response.status()}`)
      const admittedConversation = await api('/conversations/' + receipt.conversationId)
      if (admittedConversation.personaId !== journey.personaId)
        throw new Error('Stored conversation persona differs from frozen manifest')
      append(resolve(output, 'admissions.jsonl'), { case: turn.id, receipt, at: Date.now() })
      const row = {
        case: turn.id,
        prompt: turn.prompt,
        receipt,
        beforeWorks,
        expected: turn.quality,
        sentUnixMs: await page.evaluate(() => window.__perf?.startUnixMs ?? null),
        metrics: { admittedSeconds: (performance.now() - began) / 1000 },
      }
      let message
      let failure
      try {
        const deadline = performance.now() + Number(options.timeout ?? 600) * 1000
        while (performance.now() < deadline) {
          message = await api('/messages/' + receipt.messageId)
          if (terminal.has(message.job?.state)) break
          await page.waitForTimeout(250)
        }
        if (!terminal.has(message?.job?.state))
          throw new Error('Frozen observation deadline reached')
        row.message = message
        row.metrics.finalReadbackSeconds = (performance.now() - began) / 1000
        if (message.reply?.trim()) {
          await page.waitForFunction(() => window.__perf?.completePaintMs != null, null, {
            timeout: 15_000,
          })
        }
        const paint = await page.evaluate(() => ({ ...window.__perf }))
        row.sentUnixMs = paint.startUnixMs
        row.metrics.browserFirstPaintSeconds =
          paint.firstPaintMs === null ? null : paint.firstPaintMs / 1000
        row.metrics.browserCompletePaintSeconds =
          paint.completePaintMs === null ? null : paint.completePaintMs / 1000
        if (await page.getByRole('region', { name: '回答助手问题' }).isVisible()) {
          await page.evaluate(
            () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))),
          )
          row.metrics.browserInteractionReadySeconds = (performance.now() - began) / 1000
          row.metrics.humanWaitingSeconds = null
        }
        row.dependentReports = []
        if (turn.quality.kind.startsWith('report_')) {
          while (performance.now() < deadline) {
            const reports = await api('/reports?kind=weekly')
            row.dependentReports = await Promise.all(
              (reports.items ?? []).map((item) => api('/reports/' + item.id)),
            )
            if (
              !row.dependentReports.length ||
              row.dependentReports.every((item) => !['queued', 'running'].includes(item.job?.state))
            )
              break
            await page.waitForTimeout(250)
          }
          row.metrics.dependentReadySeconds = (performance.now() - began) / 1000
          const reportLink = page.getByRole('link', { name: '查看当前报告', exact: true }).last()
          if (row.dependentReports.length && (await reportLink.count())) {
            const href = await reportLink.getAttribute('href')
            const reportPage = await context.newPage()
            const opened = performance.now()
            try {
              await reportPage.goto(new URL(href, metadata.origin).href)
              await reportPage.getByRole('heading', { name: '完成的工作', exact: true }).waitFor()
              for (const value of Object.values(row.dependentReports[0].content ?? {}))
                if (String(value).trim())
                  await reportPage.getByText(String(value), { exact: true }).first().waitFor()
              await reportPage.evaluate(
                () =>
                  new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))),
              )
              row.metrics.reportOpenPaintSeconds = (performance.now() - opened) / 1000
              row.metrics.reportBrowserReadySeconds = (performance.now() - began) / 1000
              row.reportBrowser = { href, text: await reportPage.locator('body').innerText() }
              await reportPage.screenshot({ path: resolve(directory, 'report.png') })
            } finally {
              await reportPage.close()
            }
          }
        }
        row.fileChecks = []
        for (const item of message.deliverables ?? [])
          for (const file of item.files ?? []) {
            const url = file.downloadUrl ?? file.url
            if (!url) continue
            const download = await context.request.get(new URL(url, metadata.origin).href)
            const bytes = await download.body()
            const filename = `${row.fileChecks.length}-${String(file.filename ?? file.name ?? 'output').replace(/[^a-zA-Z0-9._-]/g, '_')}`
            writeFileSync(resolve(directory, filename), bytes)
            row.fileChecks.push({
              ...file,
              status: download.status(),
              size: bytes.length,
              path: filename,
              sha256: createHash('sha256').update(bytes).digest('hex'),
            })
          }
        row.metrics.usableSeconds =
          Math.max(
            row.metrics.browserCompletePaintSeconds ?? 0,
            row.metrics.dependentReadySeconds ?? 0,
            row.metrics.reportBrowserReadySeconds ?? 0,
            row.metrics.browserInteractionReadySeconds ?? 0,
            row.fileChecks.length ? (performance.now() - began) / 1000 : 0,
          ) || null
        await page.screenshot({ path: resolve(directory, 'complete.png') })
        row.browserText = await page.locator('article').last().innerText()
        writeFileSync(resolve(directory, 'answer.txt'), message.reply ?? '')
      } catch (error) {
        failure = error
        row.exception = { type: error.name, message: error.message }
        const job = await api('/jobs/' + receipt.jobId)
        if (['queued', 'running'].includes(job.state))
          await api('/jobs/' + receipt.jobId + '/cancel', 'POST', {
            expectedAttempt: job.attempt,
            expectedFence: job.fence,
          })
      } finally {
        await stopBrowserObservation(page, row)
      }
      row.afterWorks = await api('/work-items?limit=20')
      if (turn.quality.kind === 'memory') row.afterMemory = await api('/assistant/memory')
      row.persistenceReadbackSeconds = (performance.now() - began) / 1000
      row.workCommitTimes = (row.afterWorks.items ?? [])
        .filter((work) => Date.parse(work.updatedAt) >= row.sentUnixMs)
        .map((work) => ({
          id: work.id,
          revision: work.revision,
          updatedAt: work.updatedAt,
          commitSeconds: (Date.parse(work.updatedAt) - row.sentUnixMs) / 1000,
        }))
      row.actualLength = {
        hanCharacters: [...(message?.reply ?? '').matchAll(/[\u3400-\u9fff]/g)].length,
      }
      row.wallSeconds = (performance.now() - began) / 1000
      row.qualityStatus = 'pending_offline_review'
      json(resolve(directory, 'result.json'), row)
      append(resolve(output, 'results.jsonl'), row)
      rows.push(row)
      console.log(
        JSON.stringify({
          case: row.case,
          state: row.message?.job?.state,
          metrics: row.metrics,
          exception: row.exception,
        }),
      )
      if (failure || ['failed', 'cancelled', 'awaiting_retry'].includes(message?.job?.state)) break
    }
  } finally {
    json(resolve(output, 'browser-errors.json'), errors)
    await browser.close()
  }
  return rows
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const options = {}
  for (let index = 2; index < process.argv.length; index += 2)
    options[process.argv[index].replace(/^--/, '')] = process.argv[index + 1]
  await runBrowserJourney(options)
}
