// Opt-in real browser journeys. Credentials are resolved only through an owned manifest.
import { chromium } from 'playwright'
import { readFileSync, writeFileSync, appendFileSync, mkdirSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { dirname, resolve } from 'node:path'
import { api, browserEnvironment } from '../../../../eval/web/agent-browser-common.mjs'

const metadataPath = process.env.SPEC068_ENVIRONMENT
const output = process.env.SPEC068_BROWSER_OUTPUT
const previousOutput = process.env.SPEC068_PREVIOUS_OUTPUT
const suitePath = process.env.AGENT_BROWSER_SUITE
const suite = suitePath ? JSON.parse(readFileSync(suitePath, 'utf8')) : null
const repetition = Number(process.env.AGENT_BROWSER_REPETITION ?? '1')
if (![1, 2, 3].includes(repetition)) throw new Error('Invalid predeclared repetition')
if (suite && process.env.SPEC068_BROWSER_CASES) throw new Error('Suite determines its frozen cases')
const casesPath = suite
  ? resolve(dirname(suitePath), suite.browserCaseFile)
  : (process.env.SPEC068_BROWSER_CASES ?? new URL('./browser-cases.json', import.meta.url))
const caseSha256 = createHash('sha256').update(readFileSync(casesPath)).digest('hex')
if (suite && caseSha256 !== suite.browserCaseSha256)
  throw new Error('Frozen browser cases fingerprint mismatch')
if (!metadataPath || !output) throw new Error('Owned environment and unique output required')
const { metadata, state } = browserEnvironment({ metadataPath })
const cases = JSON.parse(readFileSync(casesPath, 'utf8')).filter(
  (item) =>
    (!process.env.SPEC068_CASE_IDS || process.env.SPEC068_CASE_IDS.split(',').includes(item.id)) &&
    (repetition === 1 || suite?.browserRepetition.caseIds.includes(item.id)),
)
if (!cases.length) throw new Error('No frozen browser cases selected')
mkdirSync(output, { recursive: true })
if (existsSync(`${output}/run.json`)) throw new Error('Never overwrite first results')
writeFileSync(
  `${output}/run.json`,
  JSON.stringify(
    {
      runId: metadata.runId,
      caseSha256,
      suiteRevision: suite?.revision ?? '059',
      repetition,
      applicationCommit: metadata.commit,
      channel: 'real-browser',
      startedAt: new Date().toISOString(),
      observation: 'Status GETs are harness observations, not Agent tools',
      watchdogSeconds: 1860,
    },
    null,
    2,
  ),
)
const browser = await chromium.launch()
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'])
const modes = { ask: '逐项确认', auto: '自动审核', full: '自主执行' }
const save = (path, value) => writeFileSync(path, JSON.stringify(value, null, 2))
async function records(page) {
  const result = {}
  for (const [name, path] of [
    ['work', '/api/v1/work-items'],
    ['weekly', '/api/v1/reports?kind=weekly'],
  ]) {
    const items = [],
      seen = new Set()
    let cursor
    do {
      let data
      try {
        data = await api(
          page,
          path +
            (path.includes('?') ? '&' : '?') +
            'limit=20' +
            (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''),
        )
      } catch (error) {
        if (path.startsWith('/api/v1/reports') && error.message.includes('HTTP 403:')) {
          result[name] = { status: 403, reason: 'Administrator report access is through team APIs' }
          break
        }
        throw error
      }
      items.push(...(data.items ?? []))
      cursor = data.nextCursor
      if (cursor && seen.has(cursor)) throw new Error('Readback cursor repeated')
      seen.add(cursor)
    } while (cursor)
    result[name] ??= items
  }
  result.memory = await api(page, '/api/v1/assistant/memory')
  return result
}
async function settings(page, item) {
  await page.getByRole('button', { name: /^执行权限：/ }).click()
  await page.getByRole('menuitemradio', { name: new RegExp('^' + modes[item.mode]) }).click()
  const ack = page.getByRole('dialog', { name: '开启自主执行' })
  if (await ack.isVisible())
    await ack.getByRole('button', { name: '开启自主执行', exact: true }).click()
  await page.getByRole('button', { name: /选择人设：/ }).click()
  await page
    .getByRole('menuitemradio', { name: item.persona === 'dabao' ? /^Noria人设/ : /^专业人设/ })
    .click()
  const reasoning = await api(page, '/api/v1/assistant/reasoning-settings')
  if (!reasoning.options.some((option) => option.effort === item.effort))
    throw new Error('Frozen effort not configured')
  if (reasoning.selected?.effort !== item.effort) {
    await page.getByRole('button', { name: /^思考强度：/ }).click()
    await page.getByRole('menuitemradio', { name: item.effort, exact: true }).click()
  }
  return {
    reasoning: await api(page, '/api/v1/assistant/reasoning-settings'),
    execution: await api(page, '/api/v1/assistant/execution-settings'),
  }
}
async function waitTurn(page, row, directory, step) {
  const began = Date.now(),
    receipts = [row.receipt]
  let previous = '',
    reloaded = false,
    firstVisible = false,
    cancelled = false
  while (Date.now() - began < 1860000) {
    const article = page
      .locator('article')
      .filter({ has: page.getByText(row.prompt, { exact: true }) })
      .last()
    const text = (await article.locator('[data-reply-state]').allTextContents()).at(-1) ?? ''
    const visibleImages = article.locator('[aria-label="生成图片"] img')
    if (!row.firstImageVisibleMs && (await visibleImages.count())) {
      const loaded = await visibleImages.evaluateAll((nodes) =>
        nodes.some((n) => n.complete && n.naturalWidth > 0),
      )
      if (loaded) {
        row.firstImageVisibleMs = Date.now() - row.started
        await page.screenshot({ path: `${directory}/turn-${row.turn}-first-image.png` })
      }
    }
    if (text && text !== previous) {
      row.samples.push({
        ms: Date.now() - row.started,
        characters: text.length,
        sha256: createHash('sha256').update(text).digest('hex'),
      })
      previous = text
      if (!firstVisible) {
        firstVisible = true
        row.firstVisibleMs = Date.now() - row.started
        await page.screenshot({ path: `${directory}/turn-${row.turn}-first-visible.png` })
      }
      if (step.reloadDuringStream && !reloaded) {
        reloaded = true
        row.reloadedAtMs = Date.now() - row.started
        await page.reload()
      }
    }
    const messages = await Promise.all(
      receipts.map((receipt) => api(page, '/api/v1/messages/' + receipt.messageId)),
    )
    row.message = messages.at(-1)
    row.messages = messages
    if (
      step.cancel &&
      !cancelled &&
      row.message.job?.state === 'running' &&
      Date.now() - began > 3000
    ) {
      const cancellation = page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          new URL(response.url()).pathname === `/api/v1/jobs/${row.message.job.id}/cancel`,
      )
      await page.getByRole('button', { name: '中断', exact: true }).click()
      const response = await cancellation
      row.cancellation = { status: response.status(), data: await response.json() }
      cancelled = true
      row.cancelledAtMs = Date.now() - row.started
    }
    if (messages.every((message) => terminal.has(message.job?.state))) {
      const card = messages
        .flatMap((message) => message.actions ?? [])
        .find((action) => action.canConfirm)
      if (card && step.confirmation && !row.confirmation) {
        await page.screenshot({ path: `${directory}/turn-${row.turn}-confirmation.png` })
        const section = page
          .locator('section[data-status="pending"]')
          .filter({ hasText: card.title ?? card.preview?.title ?? card.label })
          .last()
        const result = page.waitForResponse(
          (response) =>
            response.request().method() === 'POST' &&
            new URL(response.url()).pathname ===
              `/api/v1/business-actions/${card.id}/${step.confirmation}`,
        )
        await section
          .getByRole('button', {
            name:
              step.confirmation === 'cancel'
                ? '取消'
                : (card.confirmLabel ?? (/delete_/.test(card.action) ? '确认删除' : '确认执行')),
            exact: true,
          })
          .click()
        const response = await result
        const data = await response.json()
        row.confirmation = { choice: step.confirmation, status: response.status(), data }
        if (
          data.continuation &&
          !receipts.some((value) => value.messageId === data.continuation.messageId)
        )
          receipts.push(data.continuation)
        await page.waitForTimeout(500)
        continue
      }
      if (step.questionAnswer && !row.question) {
        const panel = page.getByRole('region', { name: '回答助手问题' })
        if (
          messages.some((message) =>
            message.interactions?.some((entry) => entry.state === 'waiting'),
          )
        )
          await panel.waitFor({ state: 'visible' })
        if (await panel.isVisible()) {
          await page.screenshot({ path: `${directory}/turn-${row.turn}-question.png` })
          const fields = panel.locator('fieldset')
          for (const field of await fields.all()) {
            const option = field.getByLabel(new RegExp(step.questionAnswer))
            if (await option.count()) await option.first().check()
            else if (await field.locator('textarea').count())
              await field.locator('textarea').fill(step.questionAnswer)
            else throw new Error('Requested frozen answer is absent; refusing arbitrary option')
          }
          const result = page.waitForResponse(
            (response) =>
              response.request().method() === 'POST' &&
              /\/interactions\/[^/]+\/answer$/.test(new URL(response.url()).pathname),
          )
          await panel.getByRole('button', { name: '提交回答', exact: true }).click()
          const response = await result,
            data = await response.json()
          row.question = { status: response.status(), data }
          if (
            data.continuation &&
            !receipts.some((value) => value.messageId === data.continuation.messageId)
          )
            receipts.push(data.continuation)
          await page.waitForTimeout(500)
          continue
        }
        row.question = { notDisplayed: true }
        if (step.requireQuestion)
          row.requirementFailures = [
            'Explicit question UI was not displayed; dependent turns are not sent',
          ]
      }
      row.receipts = receipts
      row.reloadDuringStreamObserved = reloaded
      return
    }
    await page.waitForTimeout(750)
  }
  throw new Error('Harness watchdog 1860 seconds exceeded; product budget is 1800 seconds')
}
async function journey(original) {
  const item = structuredClone(original)
  if (repetition > 1)
    for (const title of item.repeatTitles ?? []) {
      for (const step of item.turns)
        step.prompt = step.prompt.replaceAll(title, `${title}-r${repetition}`)
    }
  const directory = `${output}/${item.id}`
  mkdirSync(directory, { recursive: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'no-preference',
  })
  const page = await context.newPage()
  page.setDefaultTimeout(20000)
  const result = {
    case: item,
    turns: [],
    pageErrors: [],
    requests: [],
    classification: 'REVIEW_REQUIRED',
  }
  const priorPath = previousOutput && `${previousOutput}/${item.id}/result.json`
  const prior =
    priorPath && existsSync(priorPath) ? JSON.parse(readFileSync(priorPath, 'utf8')) : null
  if (prior?.turns.length) {
    for (const row of prior.turns) {
      if (
        row.error ||
        !['completed', 'needs_input', 'cancelled'].includes(row.message?.job?.taskOutcome?.state)
      )
        break
      result.turns.push(row)
    }
    result.resumedFrom = priorPath
  }
  let firstConversation
  page.on('pageerror', (error) => result.pageErrors.push(error.message))
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/messages' && request.method() === 'POST')
      result.requests.push({
        event: 'start',
        path,
        method: 'POST',
        body: request.postDataJSON(),
        time: Date.now(),
      })
  })
  page.on('response', (response) => {
    const path = new URL(response.url()).pathname
    if (path.startsWith('/api/v1/'))
      result.requests.push({
        path,
        method: response.request().method(),
        status: response.status(),
        time: Date.now(),
      })
  })
  try {
    await page.goto(state.origin)
    await page.getByRole('button', { name: /直接登录/ }).click()
    await page.getByLabel('账号', { exact: true }).fill(state.users[item.role].username)
    await page.getByLabel('密码', { exact: true }).fill(state.users[item.role].password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page
      .getByRole('navigation', { name: '工作空间', includeHidden: true })
      .waitFor({ state: 'attached' })
    await page
      .getByRole('navigation', { name: '工作空间' })
      .getByRole('link', { name: '聊天搭子', exact: true })
      .click()
    await page.getByRole('button', { name: '新会话', exact: true }).click()
    await page.waitForURL(/\/assistant\?new=1$/)
    await page.getByText('随时为你准备', { exact: true }).waitFor()
    result.settings = await settings(page, item)
    if (item.fixture === 'reference')
      result.fixture =
        prior?.fixture ??
        (await api(page, '/api/v1/work-items', 'POST', {
          title: 'B07引用资料核对',
          summary: '供应商尚未提供测试账号，无法验收',
          status: 'blocked',
          blocker: '缺少测试账号',
          nextStep: '联系供应商',
        }))
    if (item.resetMemory && !prior) {
      let memory = await api(page, '/api/v1/assistant/memory')
      if (!memory.enabled)
        memory = await api(page, '/api/v1/assistant/memory/settings', 'PATCH', {
          enabled: true,
          expectedRevision: memory.revision,
        })
      await api(page, '/api/v1/assistant/memory/document', 'PUT', {
        markdown: '',
        expectedRevision: memory.revision,
      })
    }
    result.before = prior?.before ?? (await records(page))
    if (prior?.turns[0]?.receipt) {
      firstConversation = prior.turns[0].receipt.conversationId
      const lastAccepted = prior.turns.findLast((row) => row.receipt)
      await page.goto(state.origin + '/assistant/' + lastAccepted.receipt.conversationId)
    }
    const pending = result.turns.at(-1)
    const frozenAnswer = item.turns.find((step) => step.questionAnswer)?.questionAnswer
    if (
      pending?.message?.interactions?.some((interaction) => interaction.state === 'waiting') &&
      frozenAnswer
    ) {
      const continuation = {
        ...pending,
        started: Date.now(),
        samples: [],
        question: undefined,
        resumedQuestionFrom: priorPath,
      }
      await waitTurn(page, continuation, directory, { questionAnswer: frozenAnswer })
      continuation.readback = await records(page)
      continuation.ui = await page.locator('[data-chat-content]').innerText()
      continuation.seconds = (Date.now() - continuation.started) / 1000
      result.turns[result.turns.length - 1] = continuation
      save(`${directory}/question-resumed.json`, continuation)
    }
    for (const [index, step] of item.turns.entries()) {
      if (index < result.turns.length) continue
      const row = { turn: index + 1, prompt: step.prompt, started: Date.now(), samples: [] }
      try {
        if (step.newConversation) {
          await page.getByRole('button', { name: '新会话', exact: true }).click()
          await page.waitForURL(/\/assistant\?new=1$/)
          await page.getByText('随时为你准备', { exact: true }).waitFor()
          await settings(page, item)
        }
        if (step.returnFirstConversation) {
          await page.getByRole('button', { name: '会话列表', exact: true }).click()
          await page
            .getByRole('dialog', { name: '会话列表' })
            .locator(`a[href="/assistant/${firstConversation}"]`)
            .click()
          await page.waitForURL(state.origin + '/assistant/' + firstConversation)
          await page
            .locator('[data-chat-content]')
            .getByText(item.turns[0].prompt, { exact: true })
            .waitFor()
        }
        if (step.reference) {
          await page.getByRole('button', { name: '添加附件', exact: true }).click()
          await page.getByRole('button', { name: /^引用工作/ }).click()
          await page.getByRole('button', { name: '引用 ' + step.reference, exact: true }).click()
        }
        if (step.attachment)
          await page
            .locator('input[type=file]')
            .nth(1)
            .setInputFiles({
              name: step.attachment.name,
              mimeType: 'text/plain',
              buffer: Buffer.from(step.attachment.text),
            })
        row.visiblePersona = await page
          .getByRole('button', { name: /^选择人设：/ })
          .getAttribute('aria-label')
        row.visibleMode = await page
          .getByRole('button', { name: /^执行权限：/ })
          .getAttribute('aria-label')
        if (
          item.persona === 'dabao'
            ? !row.visiblePersona.includes('Noria')
            : !row.visiblePersona.includes('专业')
        )
          throw new Error('Visible persona differs from frozen case before sending')
        if (!row.visibleMode.includes(modes[item.mode]))
          throw new Error('Visible permission differs from frozen case before sending')
        const recovery =
          process.env.SPEC068_RECOVER_ENV_FAILURES === '1' &&
          ['awaiting_retry', 'failed'].includes(prior?.turns[index]?.message?.job?.state)
        const observedReceipt = prior?.turns[index]?.error && prior.turns[index].receipt
        const editor = page.getByRole('textbox', { name: '工作消息' })
        if (!recovery && !observedReceipt) await editor.fill(step.prompt)
        if (step.offlineRetry && (recovery || observedReceipt)) {
          row.offline = prior.turns[index].offline
          row.offlineEvidenceSource = priorPath
        } else if (step.offlineRetry) {
          await context.setOffline(true)
          await page.getByRole('button', { name: '发送', exact: true }).click()
          await page.getByRole('alert').waitFor()
          row.offline = {
            draft: await editor.inputValue(),
            alerts: await page.getByRole('alert').count(),
          }
          await page.screenshot({ path: `${directory}/offline.png` })
          await page.waitForTimeout(1800)
          await context.setOffline(false)
          await page.waitForTimeout(1500)
          row.offline.restoredDraft = await editor.inputValue()
          row.offline.restoredUi = await page.locator('[data-chat-content]').innerText()
          row.offline.requests = result.requests.filter((request) => request.event === 'start')
          save(`${directory}/offline-observation.json`, row)
          await page.screenshot({ path: `${directory}/restored.png` })
        }
        if (observedReceipt) {
          row.receipt = observedReceipt
          row.observedExistingReceiptFrom = priorPath
          row.observedExistingMessage = await api(
            page,
            '/api/v1/messages/' + observedReceipt.messageId,
          )
          if (
            process.env.SPEC068_RECOVER_ENV_FAILURES === '1' &&
            ['awaiting_retry', 'failed'].includes(row.observedExistingMessage.job?.state)
          ) {
            const retried = page.waitForResponse(
              (response) =>
                response.request().method() === 'POST' &&
                new URL(response.url()).pathname === `/api/v1/jobs/${observedReceipt.jobId}/retry`,
            )
            await page.getByRole('button', { name: '重试', exact: true }).last().click()
            const response = await retried
            if (response.status() !== 200) throw new Error(`Retry HTTP ${response.status()}`)
            row.retryJob = await response.json()
            row.receipt = { ...observedReceipt, jobId: row.retryJob.id }
          }
        } else if (recovery) {
          row.recoveredFrom = priorPath
          const previousReceipt = prior.turns[index].receipt
          const retried = page.waitForResponse(
            (response) =>
              response.request().method() === 'POST' &&
              new URL(response.url()).pathname === `/api/v1/jobs/${previousReceipt.jobId}/retry`,
          )
          await page.getByRole('button', { name: '重试', exact: true }).last().click()
          const response = await retried
          if (response.status() !== 200) throw new Error(`Retry HTTP ${response.status()}`)
          row.retryJob = await response.json()
          row.receipt = { ...previousReceipt, jobId: row.retryJob.id }
        } else {
          const accepted = page.waitForResponse(
            (response) =>
              response.request().method() === 'POST' &&
              new URL(response.url()).pathname === '/api/v1/messages',
          )
          void accepted.catch(() => {})
          const retry = page.getByRole('button', { name: /^(重试|原样重试，确认结果)$/ })
          if (step.offlineRetry && (await retry.count())) await retry.first().click()
          else await page.getByRole('button', { name: '发送', exact: true }).click()
          const response = await accepted
          row.admissionStatus = response.status()
          if (response.status() !== 202) throw new Error(`Send HTTP ${response.status()}`)
          row.receipt = await response.json()
        }
        firstConversation ??= row.receipt.conversationId
        appendFileSync(
          `${directory}/accepted.jsonl`,
          JSON.stringify({ turn: row.turn, receipt: row.receipt }) + '\n',
        )
        await page.screenshot({ path: `${directory}/turn-${row.turn}-accepted.png` })
        await waitTurn(page, row, directory, step)
        row.seconds = (Date.now() - row.started) / 1000
        await page.getByRole('textbox', { name: '工作消息' }).waitFor({ state: 'visible' })
        await page.waitForTimeout(300)
        row.readback = await records(page)
        row.ui = await page.locator('[data-chat-content]').innerText()
        if (item.verifyAfterReload) {
          await page.reload()
          await page.getByRole('textbox', { name: '工作消息' }).waitFor()
          row.afterReload = {
            message: await api(page, '/api/v1/messages/' + row.message.id),
            ui: await page.locator('[data-chat-content]').innerText(),
          }
        }
        row.observationSeconds = (Date.now() - row.started) / 1000
        await page.screenshot({ path: `${directory}/turn-${row.turn}-final.png`, fullPage: true })
      } catch (error) {
        row.error = error.message
        await context.setOffline(false)
        await page.screenshot({ path: `${directory}/turn-${row.turn}-error.png` }).catch(() => {})
        if (row.receipt) {
          const job = await api(page, '/api/v1/jobs/' + row.receipt.jobId).catch(() => null)
          if (job && ['queued', 'running'].includes(job.state))
            await api(page, '/api/v1/jobs/' + job.id + '/cancel', 'POST', {
              expectedAttempt: job.attempt,
              expectedFence: job.fence,
            }).catch(() => {})
        }
      }
      result.turns.push(row)
      appendFileSync(`${directory}/first.jsonl`, JSON.stringify(row) + '\n')
      save(`${directory}/result.json`, result)
      console.log(
        JSON.stringify({
          case: item.id,
          turn: row.turn,
          state: row.message?.job?.state,
          seconds: row.seconds,
          samples: row.samples.length,
          error: row.error,
        }),
      )
      if (
        row.error ||
        row.requirementFailures?.length ||
        ['failed', 'awaiting_retry'].includes(row.message?.job?.state)
      )
        break
    }
    result.after = await records(page)
  } catch (error) {
    result.setupError = error.message
    await page.screenshot({ path: `${directory}/setup-error.png` }).catch(() => {})
    console.log(JSON.stringify({ case: item.id, setupError: error.message }))
  } finally {
    save(`${directory}/result.json`, result)
    await context.close()
  }
}
try {
  for (const item of cases) await journey(item)
} finally {
  await browser.close()
}
