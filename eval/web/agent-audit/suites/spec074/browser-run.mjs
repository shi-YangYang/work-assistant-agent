import { chromium } from 'playwright'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { api } from '../../../agent-browser-common.mjs'
const root = resolve('artifacts/spec074/20261017-real-audit'),
  output = root + '/browser'
const state = JSON.parse(readFileSync(root + '/credentials.json', 'utf8'))
const cases = JSON.parse(readFileSync(new URL('./browser-cases.json', import.meta.url), 'utf8'))
const ids = process.env.BROWSER_CASES?.split(',')
const b = await chromium.launch({
  args: [
    '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream',
    '--use-file-for-fake-audio-capture=' + root + '/materials/audio.wav',
  ],
})
const save = (p, v) => writeFileSync(p, JSON.stringify(v, null, 2))
const terminal = new Set(['succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'])
const modes = { ask: '逐项确认', auto: '自动审核', full: '自主执行' }
const sha = (s) => createHash('sha256').update(s).digest('hex')
async function records(p) {
  const r = {}
  for (const [k, path] of [
    ['work', '/api/v1/work-items?limit=20'],
    ['memory', '/api/v1/assistant/memory'],
    ['reports', '/api/v1/reports?kind=weekly&limit=20'],
  ]) {
    try {
      r[k] = await api(p, path)
    } catch (e) {
      r[k] = { error: e.message }
    }
  }
  return r
}
async function shot(p, dir, name) {
  await p.screenshot({ path: dir + '/' + name + '.png', fullPage: false })
}
async function more(p, item) {
  if (
    item.mobile &&
    (await p
      .getByRole('button', { name: '更多功能', exact: true })
      .getAttribute('aria-expanded')) !== 'true'
  )
    await p.getByRole('button', { name: '更多功能', exact: true }).click()
}
async function setup(p, item) {
  await p.goto(state.origin)
  await p.getByRole('button', { name: /直接登录/ }).click()
  await p.getByLabel('账号', { exact: true }).fill(state.users[item.role].username)
  await p.getByLabel('密码', { exact: true }).fill(state.users[item.role].password)
  const logged = p.waitForResponse(
    (r) => new URL(r.url()).pathname === '/api/v1/auth/login' && r.request().method() === 'POST',
  )
  await p.getByRole('button', { name: '登录', exact: true }).click()
  await logged
  await p.goto(state.origin + '/assistant')
  await p.getByRole('textbox', { name: '工作消息' }).waitFor()
  await p.getByRole('button', { name: '新会话', exact: true }).click()
  await p.getByRole('textbox', { name: '工作消息' }).waitFor()
  await more(p, item)
  const reason = await api(p, '/api/v1/assistant/reasoning-settings')
  if (reason.selected?.effort !== item.effort) {
    await p.getByRole('button', { name: /^思考强度：/ }).click()
    await p.getByRole('menuitemradio', { name: item.effort, exact: true }).click()
  }
  await more(p, item)
  await p.getByRole('button', { name: /^执行权限：/ }).click()
  await p.getByRole('menuitemradio', { name: new RegExp('^' + modes[item.mode]) }).click()
  const ack = p.getByRole('dialog', { name: '开启自主执行' })
  if (await ack.isVisible())
    await ack.getByRole('button', { name: '开启自主执行', exact: true }).click()
  if (
    item.mobile &&
    (await p
      .getByRole('button', { name: '更多功能', exact: true })
      .getAttribute('aria-expanded')) === 'true'
  )
    await p.getByRole('button', { name: '更多功能', exact: true }).click()
  return {
    reasoning: await api(p, '/api/v1/assistant/reasoning-settings'),
    execution: await api(p, '/api/v1/assistant/execution-settings'),
  }
}
async function upload(p, files, image = false) {
  await p
    .locator('input[type=file]')
    .nth(image ? 0 : 1)
    .setInputFiles(files)
  await p.waitForFunction(
    () =>
      ![...document.querySelectorAll('[aria-label="上传中"]')].some(
        (e) => e.getBoundingClientRect().width > 0,
      ),
    null,
    { timeout: 60000 },
  )
  await p.waitForTimeout(250)
}
async function wait(p, ctx, item, row, dir, opt = {}) {
  let prev = '',
    cancel = false,
    reload = false,
    offline = false
  const start = Date.now()
  while (Date.now() - start < 1860000) {
    row.message = await api(p, '/api/v1/messages/' + row.receipt.messageId)
    const replies = await p.locator('[data-reply-state]').allTextContents()
    const text = replies.at(-1) || ''
    if (text && text !== prev) {
      prev = text
      row.samples.push({ ms: Date.now() - row.started, length: text.length, sha256: sha(text) })
      if (!row.firstVisibleMs) {
        row.firstVisibleMs = Date.now() - row.started
        await shot(p, dir, 'turn-' + row.turn + '-first')
      }
    }
    if (opt.reloadStream && !reload && text && !terminal.has(row.message.job?.state)) {
      reload = true
      await p.reload()
      await p.getByRole('textbox', { name: '工作消息' }).waitFor()
      row.reloadStreamAtMs = Date.now() - row.started
    }
    if (opt.offline && !offline && row.message.job?.state === 'running') {
      offline = true
      await ctx.setOffline(true)
      await p.waitForTimeout(1500)
      await shot(p, dir, 'offline')
      await ctx.setOffline(false)
      row.offlineWindowMs = 1500
    }
    if (opt.cancelImage && !cancel && row.message.job?.state === 'running') {
      const content = JSON.stringify(row.message)
      if (/image\/|image-1|\.png/.test(content) && Date.now() - start > 3000) {
        await shot(p, dir, 'partial-image-before-cancel')
        await p.getByRole('button', { name: '中断', exact: true }).click()
        cancel = true
        row.cancelAtMs = Date.now() - row.started
      }
    }
    if (terminal.has(row.message.job?.state)) {
      await p.waitForTimeout(400)
      row.ui = await p.locator('body').innerText()
      row.seconds = (Date.now() - row.started) / 1000
      row.readback = await records(p)
      await shot(p, dir, 'turn-' + row.turn + '-final')
      return
    }
    await p.waitForTimeout(700)
  }
  throw Error('watchdog1860s')
}
async function send(p, ctx, item, result, dir, prompt, opt = {}) {
  const row = { turn: result.turns.length + 1, prompt, started: Date.now(), samples: [] }
  result.turns.push(row)
  await p.getByRole('textbox', { name: '工作消息' }).fill(prompt)
  const pending = p.waitForResponse(
    (r) => new URL(r.url()).pathname === '/api/v1/messages' && r.request().method() === 'POST',
  )
  void pending.catch(() => {})
  await p.getByRole('button', { name: '发送', exact: true }).click()
  const r = await pending
  row.admissionStatus = r.status()
  row.receipt = await r.json()
  save(dir + '/accepted-' + row.turn + '.json', row)
  if (r.status() !== 202) throw Error('admission' + r.status())
  await wait(p, ctx, item, row, dir, opt)
  save(dir + '/turn-' + row.turn + '.json', row)
  return row
}
async function main(item) {
  const dir =
    output + '/' + item.id + (process.env.BROWSER_ATTEMPT ? '-' + process.env.BROWSER_ATTEMPT : '')
  mkdirSync(dir, { recursive: true })
  if (existsSync(dir + '/result.json')) throw Error('Never overwrite ' + dir)
  const ctx = await b.newContext({
    viewport: item.mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
    isMobile: item.mobile,
    hasTouch: item.mobile,
    permissions: ['microphone'],
    acceptDownloads: true,
  })
  const p = await ctx.newPage()
  p.setDefaultTimeout(20000)
  const result = {
    case: item,
    startedAt: new Date().toISOString(),
    turns: [],
    pageErrors: [],
    requests: [],
    classification: 'REVIEW_REQUIRED',
  }
  p.on('pageerror', (e) => result.pageErrors.push(e.message))
  p.on('response', (r) => {
    const path = new URL(r.url()).pathname
    if (path.startsWith('/api/v1/') && r.request().method() !== 'GET')
      result.requests.push({
        path,
        status: r.status(),
        method: r.request().method(),
        time: Date.now(),
        ...(path === '/api/v1/messages' ? { body: r.request().postDataJSON() } : {}),
      })
  })
  try {
    result.settings = await setup(p, item)
    result.before = await records(p)
    if (item.id === 'B08') {
      result.fixtureCleanup = []
      for (const w of result.before.work.items ?? []) {
        if (!w.title.startsWith('合成验收工作'))
          throw Error('Unexpected peer work: refusing fixture deletion')
        const deleted = await api(p, '/api/v1/work-items/' + w.id, 'DELETE', {
          expectedRevision: w.revision,
        })
        result.fixtureCleanup.push({ id: w.id, title: w.title, deleted })
      }
      result.emptyBaseline = await records(p)
    }
    await shot(p, dir, 'initial')
    const editor = p.getByRole('textbox', { name: '工作消息' })
    if (item.id === 'B01') {
      await editor.fill('旧草稿不应保留')
      for (const label of ['梳理工作', '整理汇报', '汇报待办']) {
        await p.getByRole('button', { name: label, exact: true }).click()
        result.suggestions ??= []
        result.suggestions.push({
          label,
          value: await editor.inputValue(),
          messagePosts: result.requests.filter((x) => x.path === '/api/v1/messages').length,
        })
      }
      await shot(p, dir, 'suggestions')
      await send(p, ctx, item, result, dir, item.turns[0], { reloadStream: true })
      await p.reload()
      await editor.waitFor()
      result.refreshedUi = await p.locator('body').innerText()
      await send(p, ctx, item, result, dir, item.turns[1])
    } else if (item.id === 'B02') {
      const files = Array.from({ length: 22 }, (_, i) => ({
        name: `B074记录${String(i + 1).padStart(2, '0')}.txt`,
        mimeType: 'text/plain',
        buffer: Buffer.from(`编号 ${i + 1}，金额 ${(i + 1) * 11} 元。`),
      }))
      await upload(p, files.slice(0, 9))
      await p.getByRole('article', { name: 'B074记录01.txt', exact: true }).hover()
      await p.getByRole('button', { name: '移除B074记录01.txt', exact: true }).click()
      await upload(p, [files[0]])
      result.uploadOnlyPosts = result.requests.filter((x) => x.path === '/api/v1/messages').length
      await shot(p, dir, 'first-nine-uploaded')
      await send(
        p,
        ctx,
        item,
        result,
        dir,
        '先读取这第一批9份记录，记住各自编号和金额，只简短确认已读取。',
      )
      await upload(p, files.slice(9, 18))
      await send(p, ctx, item, result, dir, '这是第二批9份记录，读取编号和金额，只简短确认已读取。')
      await upload(p, files.slice(18))
      await send(p, ctx, item, result, dir, item.turns[0])
      await p.reload()
      await editor.waitFor()
      await send(p, ctx, item, result, dir, item.turns[1])
    } else if (item.id === 'B03') {
      await upload(p, [
        {
          name: 'B074禁止.exe',
          mimeType: 'application/octet-stream',
          buffer: Buffer.from('not executable test'),
        },
      ])
      result.rejection = await p.locator('body').innerText()
      await shot(p, dir, 'rejected')
      await p.getByRole('button', { name: '知道了', exact: true }).click()
      await upload(p, [root + '/materials/inventory.png'], true)
      await upload(p, [root + '/materials/brief.txt', root + '/materials/audio.wav'])
      await shot(p, dir, 'mixed-ready')
      await send(p, ctx, item, result, dir, item.turns[0])
    } else if (item.id === 'B04') {
      await editor.fill('这段文字必须保留在草稿，不能随长按语音发送')
      await p.getByRole('button', { name: '切换到语音输入', exact: true }).click()
      const button = p.getByRole('button', { name: '点击录音，长按发送', exact: true })
      let box = await button.boundingBox()
      await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      await p.mouse.down()
      await p.waitForTimeout(1200)
      await p.mouse.move(box.x + box.width / 2, box.y - 100)
      await shot(p, dir, 'hold-cancel')
      await p.mouse.up()
      await p.waitForTimeout(400)
      result.cancelPosts = result.requests.filter((x) => x.path === '/api/v1/messages').length
      box = await button.boundingBox()
      const accepted = p.waitForResponse(
        (r) => new URL(r.url()).pathname === '/api/v1/messages' && r.request().method() === 'POST',
        { timeout: 30000 },
      )
      await p.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      await p.mouse.down()
      await p.waitForTimeout(4200)
      await shot(p, dir, 'hold-send')
      await p.mouse.up()
      const res = await accepted
      const row = {
        turn: 1,
        started: Date.now(),
        samples: [],
        receipt: await res.json(),
        admissionStatus: res.status(),
        prompt: '[真实录音直发]',
      }
      result.turns.push(row)
      await wait(p, ctx, item, row, dir)
      const textMode = p.getByRole('button', { name: '切换到文字输入', exact: true })
      if (await textMode.count()) await textMode.click()
      result.remainingDraft = await editor.inputValue()
      await p.getByRole('button', { name: '转文字', exact: true }).last().click()
      await shot(p, dir, 'transcript')
      await p.getByRole('button', { name: '改文字', exact: true }).last().click()
      await p
        .getByRole('textbox', { name: '语音文字', exact: true })
        .fill('明天下午三点到会议室B参加培训。')
      const corrected = p.waitForResponse(
        (r) => r.request().method() !== 'GET' && /transcript/.test(r.url()),
      )
      await p.getByRole('button', { name: '保存修正', exact: true }).click()
      const response = await corrected
      result.correction = { status: response.status(), body: await response.json() }
      await p.waitForTimeout(800)
      result.afterCorrection = await api(p, '/api/v1/messages/' + row.receipt.messageId)
      await shot(p, dir, 'corrected')
    } else if (item.id === 'B05') {
      await upload(p, [root + '/materials/inspection.docx', root + '/materials/workflow.pptx'])
      for (const t of item.turns) await send(p, ctx, item, result, dir, t)
    } else if (item.id === 'B06') {
      await send(p, ctx, item, result, dir, item.turns[0])
      const works = (await records(p)).work.items
      const work = works.find((x) => x.title === 'B074清单验收')
      if (!work) throw Error('workmissing')
      result.workId = work.id
      const chat = p.url()
      await p.goto(state.origin + '/work/' + work.id)
      await p.getByRole('checkbox').first().waitFor()
      result.checkboxesBefore = await p
        .getByRole('checkbox')
        .evaluateAll((a) =>
          a.map((e) => ({ label: e.getAttribute('aria-label'), checked: e.checked })),
        )
      const checked = p.waitForResponse(
        (r) => r.request().method() === 'PATCH' && r.url().includes('/work-items/' + work.id),
      )
      void checked.catch(() => {})
      await p.getByRole('checkbox').first().click()
      await checked
      await p.waitForFunction(
        () => document.querySelector('input[type=checkbox]')?.checked === true,
      )
      await shot(p, dir, 'checked-first')
      result.workAfterCheck = await api(p, '/api/v1/work-items/' + work.id)
      await p.goto(chat)
      await editor.waitFor()
      await send(p, ctx, item, result, dir, item.turns[1])
    } else if (item.id === 'B07') {
      await send(p, ctx, item, result, dir, item.turns[0])
      await upload(p, [
        {
          name: 'B074材料.txt',
          mimeType: 'text/plain',
          buffer: Buffer.from('B074材料：培训资料验收口令为银杏42。'),
        },
      ])
      await send(p, ctx, item, result, dir, item.turns[1])
      result.savedWork = (await records(p)).work.items.find((x) => x.title === 'B074方案乙')
      result.sourceConversation = result.turns[0].receipt.conversationId
      await p.getByRole('button', { name: '会话列表', exact: true }).click()
      await shot(p, dir, 'conversation-list')
      result.followupRequired = 'delete source via displayed UI and read work material'
    } else if (item.id === 'B08') {
      for (const t of item.turns) await send(p, ctx, item, result, dir, t)
      result.reports = (await records(p)).reports
      const report = result.reports.items?.[0]
      if (report) {
        result.reportId = report.id
        await p.goto(state.origin + '/reports/' + report.id)
        await shot(p, dir, 'report-draft')
        result.followupRequired = 'edit report and submit through UI'
      }
    } else if (item.id === 'B09') {
      for (const t of item.turns) await send(p, ctx, item, result, dir, t)
    } else if (item.id === 'B10') {
      await send(p, ctx, item, result, dir, item.turns[0], { cancelImage: true })
      await p.reload()
      await editor.waitFor()
      await shot(p, dir, 'image-refreshed')
      result.imageUi = await p.locator('body').innerText()
      result.followupRequired = 'preview and download successful image if available'
    } else if (item.id === 'B11') {
      await send(p, ctx, item, result, dir, item.turns[0])
      await send(p, ctx, item, result, dir, item.turns[1])
      const chat = p.url()
      await p.goto(state.origin + '/work')
      await p.goto(chat)
      await editor.waitFor()
      await shot(p, dir, 'return-chat')
      result.followupRequired = 'download generated CSV and verify rows'
    } else if (item.id === 'B12') {
      await send(p, ctx, item, result, dir, item.turns[0])
      const region = p.getByRole('region', { name: '回答助手问题' })
      if (await region.isVisible()) {
        await region.getByLabel(/^线上/).first().check()
        const answer = p.waitForResponse(
          (r) =>
            /\/interactions\/[^/]+\/answer$/.test(new URL(r.url()).pathname) &&
            r.request().method() === 'POST',
        )
        await region.getByRole('button', { name: '提交回答', exact: true }).click()
        const response = await answer
        result.answer = await response.json()
        await p.waitForTimeout(2000)
      }
      await send(p, ctx, item, result, dir, item.turns[1], { offline: true })
      result.followupRequired = 'confirm pending operation through UI and read back'
    }
    result.after = await records(p)
    result.finalUi = await p.locator('body').innerText()
    await shot(p, dir, 'final')
  } catch (e) {
    result.error = { message: e.message, stack: e.stack }
    result.classification = 'ERROR_REVIEW'
    try {
      result.errorUi = await p.locator('body').innerText()
      await shot(p, dir, 'error')
    } catch {
      // Preserve the original driver error if its diagnostic screenshot also fails.
    }
  } finally {
    result.finishedAt = new Date().toISOString()
    save(dir + '/result.json', result)
    await ctx.close()
    console.log(
      JSON.stringify({
        id: item.id,
        turns: result.turns.map((t) => ({
          state: t.message?.job?.state,
          seconds: t.seconds,
          id: t.receipt?.messageId,
        })),
        error: result.error?.message,
        dir,
      }),
    )
  }
}
try {
  for (const item of cases.filter((x) => !ids || ids.includes(x.id))) await main(item)
} finally {
  await b.close()
}
