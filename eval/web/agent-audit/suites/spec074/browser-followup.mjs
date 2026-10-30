// Continue existing real browser journeys after selector/readback adaptation. Never replay replies.
import { chromium } from 'playwright'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { api } from '../../../agent-browser-common.mjs'
const root = resolve('artifacts/spec074/20261017-real-audit'),
  s = JSON.parse(readFileSync(root + '/credentials.json'))
const id = process.env.BROWSER_FOLLOWUP,
  source = root + '/browser/' + id + '-driver2/result.json',
  old = JSON.parse(readFileSync(source)),
  out =
    root +
    '/browser/' +
    id +
    '-followup' +
    (process.env.FOLLOWUP_ATTEMPT ? '-' + process.env.FOLLOWUP_ATTEMPT : '')
mkdirSync(out, { recursive: true })
if (existsSync(out + '/result.json')) throw Error('Do not overwrite result')
const result = { id, source, startedAt: new Date().toISOString(), turns: [], requests: [] }
const b = await chromium.launch()
const c = await b.newContext({
  viewport: old.case.mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
  isMobile: old.case.mobile,
  hasTouch: old.case.mobile,
  acceptDownloads: true,
})
const p = await c.newPage()
p.setDefaultTimeout(20000)
const save = (n, v) => writeFileSync(out + '/' + n + '.json', JSON.stringify(v, null, 2))
const shot = async (n) => p.screenshot({ path: out + '/' + n + '.png' })
p.on('response', (r) => {
  if (new URL(r.url()).pathname.startsWith('/api/v1/'))
    result.requests.push({
      path: new URL(r.url()).pathname,
      method: r.request().method(),
      status: r.status(),
      time: Date.now(),
    })
})
async function login() {
  await p.goto(s.origin)
  await p.getByRole('button', { name: /直接登录/ }).click()
  await p.getByLabel('账号', { exact: true }).fill(s.users[old.case.role].username)
  await p.getByLabel('密码', { exact: true }).fill(s.users[old.case.role].password)
  const logged = p.waitForResponse((r) => r.url().endsWith('/api/v1/auth/login'))
  await p.getByRole('button', { name: '登录', exact: true }).click()
  await logged
  await p.goto(
    s.origin +
      (id === 'B07' ? '/assistant?new=1' : '/assistant/' + old.turns[0].receipt.conversationId),
  )
  await p.getByRole('textbox', { name: '工作消息' }).waitFor()
}
async function wait(row) {
  const began = Date.now()
  while (Date.now() - began < 1860000) {
    row.message = await api(p, '/api/v1/messages/' + row.receipt.messageId)
    if (
      ['succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'].includes(
        row.message.job?.state,
      )
    ) {
      await p.waitForTimeout(300)
      row.seconds = (Date.now() - row.started) / 1000
      row.ui = await p.locator('body').innerText()
      await shot('turn-' + result.turns.length)
      return
    }
    await p.waitForTimeout(750)
  }
  throw Error('watchdog1860s')
}
async function send(text) {
  const row = { started: Date.now(), prompt: text }
  result.turns.push(row)
  await p.getByRole('textbox', { name: '工作消息' }).fill(text)
  const r = p.waitForResponse(
    (r) => r.url().endsWith('/api/v1/messages') && r.request().method() === 'POST',
  )
  void r.catch(() => {})
  await p.getByRole('button', { name: '发送', exact: true }).click()
  const response = await r
  row.receipt = await response.json()
  save('accepted-' + result.turns.length, row)
  await wait(row)
  return row
}
async function download(button, name) {
  const pending = p.waitForEvent('download')
  void pending.catch(() => {})
  await button.click()
  const d = await pending
  const path = out + '/' + name + '-' + d.suggestedFilename()
  await d.saveAs(path)
  const data = readFileSync(path)
  return {
    name: d.suggestedFilename(),
    path,
    bytes: data.length,
    sha256: createHash('sha256').update(data).digest('hex'),
    ...(d.suggestedFilename().endsWith('.csv') || d.suggestedFilename().endsWith('.txt')
      ? { text: data.toString('utf8') }
      : {}),
  }
}
try {
  await login()
  await shot('resumed')
  if (id === 'B04') {
    result.before = await api(p, '/api/v1/messages/' + old.turns[0].receipt.messageId)
    await p.getByRole('button', { name: '转文字', exact: true }).last().click()
    await shot('transcript')
    await p.getByRole('button', { name: '改文字', exact: true }).last().click()
    await p
      .getByRole('textbox', { name: '语音文字', exact: true })
      .fill('明天下午三点到会议室B参加培训。')
    const corrected = p.waitForResponse(
      (r) => r.request().method() === 'PATCH' && r.url().endsWith('/transcript'),
    )
    await p.getByRole('button', { name: '保存修正', exact: true }).click()
    const response = await corrected
    result.correction = { status: response.status(), message: await response.json() }
    await shot('corrected')
    result.after = await api(p, '/api/v1/messages/' + old.turns[0].receipt.messageId)
    result.work = await api(p, '/api/v1/work-items?limit=20')
  } else if (id === 'B06') {
    const w = (await api(p, '/api/v1/work-items?limit=20')).items.find(
      (w) => w.title === 'B074清单验收',
    )
    if (!w) throw Error('Expected work absent')
    result.before = await api(p, '/api/v1/work-items/' + w.id)
    const chat = p.url()
    await p.goto(s.origin + '/work/' + w.id)
    await p.getByRole('checkbox').first().waitFor()
    result.checkboxesBefore = await p
      .getByRole('checkbox')
      .evaluateAll((a) =>
        a.map((e) => ({ label: e.getAttribute('aria-label'), checked: e.checked })),
      )
    if (!(await p.getByRole('checkbox').first().isChecked())) {
      const changed = p.waitForResponse(
        (r) => r.request().method() === 'PATCH' && r.url().includes('/work-items/' + w.id),
      )
      void changed.catch(() => {})
      await p.getByRole('checkbox').first().click()
      await changed
      await p.waitForFunction(
        () => document.querySelector('input[type="checkbox"]')?.checked === true,
      )
    }
    result.afterCheck = await api(p, '/api/v1/work-items/' + w.id)
    await shot('checked')
    await p.goto(chat)
    await p.getByRole('textbox', { name: '工作消息' }).waitFor()
    await send(old.case.turns[1])
  } else if (id === 'B07') {
    const w = (await api(p, '/api/v1/work-items?limit=20')).items.find(
      (w) => w.title === 'B074方案乙',
    )
    if (!w) throw Error('Expected work absent')
    result.workBefore = await api(p, '/api/v1/work-items/' + w.id)
    result.materialsBefore = await api(p, '/api/v1/work-items/' + w.id + '/materials?limit=20')
    await p.getByRole('button', { name: '会话列表', exact: true }).click()
    const link = p.locator(`a[href="/assistant/${old.turns[0].receipt.conversationId}"]`)
    await p.waitForTimeout(300)
    if (await link.count()) {
      await link
        .locator('..')
        .getByRole('button', { name: /^删除会话：/ })
        .click()
      await p
        .getByRole('dialog', { name: '删除会话', exact: true })
        .getByRole('button', { name: '确认删除', exact: true })
        .click()
      await p.waitForTimeout(500)
    } else result.sourceConversationAlreadyDeleted = true
    try {
      result.sourceConversationReadback = await api(
        p,
        '/api/v1/conversations/' + old.turns[0].receipt.conversationId,
      )
    } catch (e) {
      result.sourceConversationReadback = { error: e.message }
    }
    await p.goto(s.origin + '/work/' + w.id)
    await p.getByRole('heading', { name: w.title, exact: true }).waitFor()
    result.workAfter = await api(p, '/api/v1/work-items/' + w.id)
    result.materialsAfter = await api(p, '/api/v1/work-items/' + w.id + '/materials?limit=20')
    await shot('work-after-source-deletion')
    result.ui = await p.locator('body').innerText()
    await p.getByRole('button', { name: '管理工作', exact: true }).click()
    await p.getByRole('menuitem', { name: /^全部附件/ }).click()
    await p.getByRole('button', { name: 'B074材料.txt', exact: true }).click()
    await shot('material-preview')
    save('before-download', result)
    const button = p.getByRole('link', { name: '下载原文件', exact: true })
    if (await button.count()) result.download = await download(button.first(), 'work-material')
    else {
      const btn = p.getByRole('button', { name: '下载原文件', exact: true })
      result.download = await download(btn.first(), 'work-material')
    }
  } else if (id === 'B08') {
    const reports = await api(p, '/api/v1/reports?kind=weekly&limit=20')
    const r = reports.items[0]
    if (!r) throw Error('Report absent')
    result.before = await api(p, '/api/v1/reports/' + r.id)
    await p.goto(s.origin + '/reports/' + r.id)
    await p.getByRole('button', { name: '编辑草稿', exact: true }).click()
    const field = p.getByLabel('下一步计划', { exact: true })
    await field.fill((await field.inputValue()) + '\nB074人工补充：明天核对第12份问卷。')
    const saved = p.waitForResponse(
      (x) =>
        x.request().method() === 'PATCH' && new URL(x.url()).pathname === '/api/v1/reports/' + r.id,
    )
    void saved.catch(() => {})
    await p.getByRole('button', { name: '保存草稿', exact: true }).click()
    await saved
    await p.getByRole('button', { name: '提交报告', exact: true }).click()
    await p
      .getByRole('dialog', { name: '提交报告', exact: true })
      .getByRole('button', { name: '确认提交', exact: true })
      .click()
    await p.waitForTimeout(500)
    result.after = await api(p, '/api/v1/reports/' + r.id)
    await shot('submitted')
  } else if (id === 'B10') {
    result.message = await api(p, '/api/v1/messages/' + old.turns[0].receipt.messageId)
    result.buttons = await p
      .locator('button')
      .evaluateAll((a) =>
        a.map((x) => ({ label: x.getAttribute('aria-label'), text: x.innerText })),
      )
    const preview = p.getByRole('button', { name: /^预览/ }).first()
    if (!(await preview.count())) throw Error('No successful image to preview')
    await preview.click()
    await shot('preview')
    const dl = p.getByRole('button', { name: /^下载/ }).last()
    result.download = await download(dl, 'image')
  } else if (id === 'B11') {
    result.buttons = await p
      .locator('button')
      .evaluateAll((a) =>
        a.map((x) => ({ label: x.getAttribute('aria-label'), text: x.innerText })),
      )
    result.downloads = []
    for (const button of await p.getByRole('button', { name: /^下载.*\.csv$/ }).all())
      result.downloads.push(await download(button, 'file' + result.downloads.length))
    if (!result.downloads.length) {
      const link = p.getByRole('button', { name: /^查看.*B074/ }).last()
      if (await link.count()) await link.click()
      result.openedUi = await p.locator('body').innerText()
      for (const button of await p.getByRole('button', { name: /^下载.*\.csv$/ }).all())
        result.downloads.push(await download(button, 'file' + result.downloads.length))
    }
    if (!result.downloads.length) throw Error('No downloadable CSV button')
    await shot('downloads')
  } else if (id === 'B12') {
    result.current = await api(p, '/api/v1/messages/' + old.turns.at(-1).receipt.messageId)
    const pending = p.locator('section[data-status="pending"]').last()
    await pending.waitFor()
    await shot('confirmation')
    const accepted = p.waitForResponse(
      (r) =>
        r.request().method() === 'POST' &&
        /\/business-actions\/[^/]+\/confirm$/.test(new URL(r.url()).pathname),
    )
    const action = result.current.actions.find((item) => item.state === 'pending')
    await pending.getByRole('button', { name: action.confirmLabel, exact: true }).click()
    const response = await accepted
    result.confirmation = await response.json()
    if (result.confirmation.continuation) {
      const row = {
        started: Date.now(),
        receipt: result.confirmation.continuation,
        prompt: '[用户点击确认]',
      }
      result.turns.push(row)
      await wait(row)
    }
    result.work = await api(p, '/api/v1/work-items?limit=20')
    await shot('confirmed')
  }
  result.finalUi = await p.locator('body').innerText()
} catch (e) {
  result.error = { message: e.message, stack: e.stack }
  result.errorUi = await p.locator('body').innerText()
  await shot('error')
} finally {
  result.finishedAt = new Date().toISOString()
  save('result', result)
  await b.close()
  console.log(JSON.stringify({ id, error: result.error?.message, turns: result.turns.length }))
}
