// Natural follow-ups preserve earlier failed evidence; all messages use the real UI/model.
import { chromium } from 'playwright'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { api } from '../../../agent-browser-common.mjs'
const root = resolve('artifacts/spec074/20261017-real-audit')
const state = JSON.parse(readFileSync(root + '/credentials.json'))
const id = process.env.BROWSER_RECOVERY
const definitions = {
  B07: {
    role: 'employee',
    effort: 'high',
    expected: ['新会话实际读取工作保存的材料副本', '独有原文真值正确，不改工作'],
    prompts: [
      '请在我的工作中找到B074方案乙，实际读取保存在这项工作里的B074材料.txt附件原文，并告诉我文件中的验收口令。不要只根据工作标题或聊天总结回答，也不要修改工作。',
    ],
  },
  B08: {
    role: 'peer',
    effort: 'low',
    conversation: '22b3ade8-844c-42a2-aaed-a3c6392b5a45',
    expected: [
      '独立新增当日进展而非仅改正文',
      '周报包含12份问卷和2处重复',
      '人工编辑后提交一次，状态与版本正确',
    ],
    prompts: [
      '请给我的工作B074报告来源新增今天的进展记录：已整理12份合成问卷，发现2处重复；下一步明天完成复核。请作为今天的工作进展保存，不要只修改工作说明，暂时不要生成报告。',
      '现在请基于我的本周工作进展，生成本周周报草稿，先不要提交。',
    ],
  },
  SSE: {
    role: 'employee',
    effort: 'low',
    expected: ['真实SSE中两条delta重排和重复后，刷新恢复', '最终UI与持久正文完全一致，不重复发送'],
    prompts: [
      '请写一篇适合下班后阅读的放松小短文，用八个编号段落，每段两三句话，内容围绕散步、听音乐、整理房间和休息。不创建工作。',
    ],
  },
}
definitions.B08FINAL = {
  ...definitions.B08,
  prompts: [],
  expected: ['保留先前生成中编辑的结果；采用真实模型候选后编辑提交'],
}
const spec = definitions[id]
if (!spec) throw Error('Unknown recovery')
const out =
  root +
  '/browser/' +
  id +
  '-recovery' +
  (process.env.RECOVERY_ATTEMPT ? '-' + process.env.RECOVERY_ATTEMPT : '')
if (existsSync(out + '/result.json')) throw Error('Never overwrite evidence')
mkdirSync(out, { recursive: true })
const result = { id, spec, startedAt: new Date().toISOString(), turns: [], requests: [], sse: [] }
writeFileSync(
  out + '/frozen.json',
  JSON.stringify({ id, spec, frozenAt: result.startedAt }, null, 2),
)
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
page.setDefaultTimeout(20000)
if (id === 'SSE') {
  await page.exposeFunction('recordSpec074Sse', (event) =>
    result.sse.push({ ...event, observedAt: Date.now() }),
  )
  await page.addInitScript(() => {
    const add = EventSource.prototype.addEventListener
    EventSource.prototype.addEventListener = function (type, listener, options) {
      if (
        type !== 'reply_delta' ||
        typeof listener !== 'function' ||
        sessionStorage.getItem('spec074-sse-injected')
      )
        return add.call(this, type, listener, options)
      let held = null
      let done = false
      return add.call(
        this,
        type,
        function (event) {
          void window.recordSpec074Sse({ kind: 'received', type, data: event.data })
          const deliver = (incoming, note) => {
            void window.recordSpec074Sse({ kind: 'delivered', type, data: incoming.data, note })
            listener.call(this, incoming)
          }
          if (done) {
            deliver(event, 'native-following')
            return
          }
          if (!held) {
            held = event
            return
          }
          deliver(event, 'out-of-order-newer')
          deliver(event, 'duplicate-newer')
          deliver(held, 'delayed-older')
          held = null
          done = true
          sessionStorage.setItem('spec074-sse-injected', '1')
          void window.recordSpec074Sse({ kind: 'injection-complete' })
        },
        options,
      )
    }
  })
}
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
const shot = (name) => page.screenshot({ path: out + '/' + name + '.png' })
const save = () => writeFileSync(out + '/result.json', JSON.stringify(result, null, 2))
try {
  await page.goto(state.origin)
  await page.getByRole('button', { name: /直接登录/ }).click()
  await page.getByLabel('账号', { exact: true }).fill(state.users[spec.role].username)
  await page.getByLabel('密码', { exact: true }).fill(state.users[spec.role].password)
  const logged = page.waitForResponse((r) => r.url().endsWith('/api/v1/auth/login'))
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await logged
  await page.goto(
    state.origin + (spec.conversation ? '/assistant/' + spec.conversation : '/assistant?new=1'),
  )
  await page.getByRole('textbox', { name: '工作消息' }).waitFor()
  if (!spec.conversation) await page.getByRole('button', { name: '新会话', exact: true }).click()
  await page.getByRole('button', { name: /^思考强度：/ }).click()
  await page.getByRole('menuitemradio', { name: spec.effort, exact: true }).click()
  await page.getByRole('button', { name: /^执行权限：/ }).click()
  await page.getByRole('menuitemradio', { name: /^自主执行/ }).click()
  const ack = page.getByRole('dialog', { name: '开启自主执行' })
  if (await ack.isVisible())
    await ack.getByRole('button', { name: '开启自主执行', exact: true }).click()
  result.before = {
    work: await api(page, '/api/v1/work-items?limit=20'),
    reports: await api(page, '/api/v1/reports?kind=weekly&limit=20'),
  }
  for (const prompt of spec.prompts) {
    const row = { prompt, started: Date.now(), samples: [] }
    result.turns.push(row)
    await page.getByRole('textbox', { name: '工作消息' }).fill(prompt)
    const accepted = page.waitForResponse(
      (r) => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/v1/messages',
    )
    void accepted.catch(() => {})
    await page.getByRole('button', { name: '发送', exact: true }).click()
    const response = await accepted
    row.admissionStatus = response.status()
    row.receipt = await response.json()
    save()
    let reloaded = false
    const began = Date.now()
    while (Date.now() - began < 1860000) {
      row.message = await api(page, '/api/v1/messages/' + row.receipt.messageId)
      const text = (await page.locator('[data-reply-state]').allTextContents()).at(-1) ?? ''
      if (text && !row.firstVisibleMs) row.firstVisibleMs = Date.now() - row.started
      if (id === 'SSE' && !reloaded && result.sse.some((e) => e.kind === 'injection-complete')) {
        reloaded = true
        await shot('after-reorder')
        row.reloadAtMs = Date.now() - row.started
        await page.reload()
        await page.getByRole('textbox', { name: '工作消息' }).waitFor()
        row.nativeConnectionRestored = true
      }
      if (
        ['succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'].includes(
          row.message.job?.state,
        )
      )
        break
      await page.waitForTimeout(500)
    }
    row.seconds = (Date.now() - row.started) / 1000
    row.ui = await page.locator('body').innerText()
    await shot('turn-' + result.turns.length)
    save()
  }
  result.after = {
    work: await api(page, '/api/v1/work-items?limit=20'),
    reports: await api(page, '/api/v1/reports?kind=weekly&limit=20'),
  }
  if (id === 'B08' || id === 'B08FINAL') {
    const report =
      result.after.reports.items.find((r) => r.kind === 'weekly') ?? result.after.reports.items[0]
    if (!report) throw Error('Natural recovery did not create report')
    result.reportBefore = await api(page, '/api/v1/reports/' + report.id)
    const reportWaitStarted = Date.now()
    while (
      ['queued', 'running'].includes(result.reportBefore.job?.state) &&
      Date.now() - reportWaitStarted < 1860000
    ) {
      await page.waitForTimeout(700)
      result.reportBefore = await api(page, '/api/v1/reports/' + report.id)
    }
    if (['queued', 'running', 'failed', 'cancelled'].includes(result.reportBefore.job?.state))
      throw Error('Report generation not complete')
    await page.goto(state.origin + '/reports/' + report.id)
    const adopt = page.getByRole('button', { name: '采用生成结果', exact: true })
    if (result.reportBefore.candidate) {
      await adopt.waitFor()
      await shot('candidate-before-adoption')
      page.once('dialog', (dialog) => dialog.accept())
      const adopted = page.waitForResponse(
        (r) => r.request().method() === 'POST' && r.url().includes('/reports/' + report.id + '/'),
      )
      void adopted.catch(() => {})
      await adopt.click()
      await adopted
      result.reportAdopted = await api(page, '/api/v1/reports/' + report.id)
      await page.reload()
    }
    await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
    const next = page.getByRole('textbox', { name: /^下一步计划/ })
    await next.fill((await next.inputValue()) + '\nB074人工补充：明天核对第12份问卷。')
    const saved = page.waitForResponse(
      (r) =>
        r.request().method() === 'PATCH' &&
        new URL(r.url()).pathname === '/api/v1/reports/' + report.id,
    )
    void saved.catch(() => {})
    await page.getByRole('button', { name: '保存草稿', exact: true }).click()
    await saved
    result.reportEdited = await api(page, '/api/v1/reports/' + report.id)
    await shot('edited')
    await page.getByRole('button', { name: '提交报告', exact: true }).click()
    const submitted = page.waitForResponse(
      (r) =>
        r.request().method() === 'POST' && r.url().includes('/reports/' + report.id + '/submit'),
    )
    void submitted.catch(() => {})
    await page
      .getByRole('dialog', { name: '提交报告', exact: true })
      .getByRole('button', { name: '确认提交', exact: true })
      .click()
    await submitted
    result.reportSubmitted = await api(page, '/api/v1/reports/' + report.id)
    await page.waitForTimeout(400)
    await shot('submitted')
  }
  result.finalUi = await page.locator('body').innerText()
  await shot('final')
} catch (error) {
  result.error = { message: error.message, stack: error.stack }
  result.errorUi = await page.locator('body').innerText()
  await shot('error')
} finally {
  result.finishedAt = new Date().toISOString()
  save()
  await browser.close()
  console.log(JSON.stringify({ id, error: result.error?.message, turns: result.turns.length }))
}
