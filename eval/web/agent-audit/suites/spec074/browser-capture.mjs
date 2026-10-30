// Read-only evidence after real UI runs; never creates messages or model responses.
import { chromium } from 'playwright'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { api } from '../../../agent-browser-common.mjs'

const root = resolve('artifacts/spec074/20261017-real-audit')
const state = JSON.parse(readFileSync(root + '/credentials.json'))
const selected = process.env.BROWSER_CAPTURE?.split(',')
const folders = [
  'B01',
  'B02-driver3',
  'B03-driver2',
  'B04-driver2',
  'B05-driver2',
  'B06-driver2',
  'B07-driver2',
  'B08-driver2',
  'B09-driver2',
  'B10-driver2',
  'B11-driver2',
  'B12-driver2',
  'SSE-recovery',
]
const browser = await chromium.launch()
try {
  for (const folder of folders) {
    const original = JSON.parse(readFileSync(root + '/browser/' + folder + '/result.json'))
    original.case ??= { ...original.spec, id: original.id, mobile: false }
    const id = original.case.id
    if (selected && !selected.includes(id)) continue
    const dir =
      root +
      '/browser/' +
      id +
      '-readback' +
      (process.env.CAPTURE_ATTEMPT ? '-' + process.env.CAPTURE_ATTEMPT : '')
    if (existsSync(dir + '/result.json')) throw Error('Do not overwrite evidence: ' + id)
    mkdirSync(dir, { recursive: true })
    const context = await browser.newContext({
      viewport: original.case.mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
      isMobile: original.case.mobile,
      hasTouch: original.case.mobile,
    })
    const page = await context.newPage()
    page.setDefaultTimeout(20000)
    const result = {
      id,
      source: folder,
      startedAt: new Date().toISOString(),
      messages: [],
      requests: [],
    }
    page.on('response', (response) => {
      const path = new URL(response.url()).pathname
      if (path.startsWith('/api/v1/'))
        result.requests.push({
          path,
          method: response.request().method(),
          status: response.status(),
        })
    })
    try {
      await page.goto(state.origin)
      await page.getByRole('button', { name: /直接登录/ }).click()
      await page.getByLabel('账号', { exact: true }).fill(state.users[original.case.role].username)
      await page.getByLabel('密码', { exact: true }).fill(state.users[original.case.role].password)
      const logged = page.waitForResponse((r) => r.url().endsWith('/api/v1/auth/login'))
      await page.getByRole('button', { name: '登录', exact: true }).click()
      await logged
      const conversationId = original.turns[0].receipt.conversationId
      await page.goto(
        state.origin + (id === 'B07' ? '/assistant?new=1' : '/assistant/' + conversationId),
      )
      await page.getByRole('textbox', { name: '工作消息' }).waitFor()
      for (const turn of original.turns) {
        try {
          result.messages.push(await api(page, '/api/v1/messages/' + turn.receipt.messageId))
        } catch (error) {
          result.messages.push({ id: turn.receipt.messageId, error: error.message })
        }
      }
      result.work = await api(page, '/api/v1/work-items?limit=20')
      result.workDetails = []
      for (const work of result.work.items.filter((w) => w.title.includes('B074'))) {
        result.workDetails.push(await api(page, '/api/v1/work-items/' + work.id))
      }
      result.reports = original.case.role.includes('admin')
        ? { notApplicable: '管理员通过团队查看员工报告' }
        : await api(page, '/api/v1/reports?kind=weekly&limit=20')
      if (id === 'B07') {
        const work = result.work.items.find((w) => w.title === 'B074方案乙')
        await page.goto(state.origin + '/work/' + work.id)
        await page.getByRole('heading', { name: work.title, exact: true }).waitFor()
      } else {
        const bottom = page.getByRole('button', { name: /有新回复.*回到最新/ })
        if (await bottom.count()) await bottom.click()
        const lastMessage = page.locator('[data-chat-content]')
        if (await lastMessage.count())
          await lastMessage.evaluate((element) => {
            let parent = element
            while (parent && parent.scrollHeight <= parent.clientHeight)
              parent = parent.parentElement
            if (parent) parent.scrollTop = parent.scrollHeight
          })
        await page.getByRole('textbox', { name: '工作消息' }).press('Escape')
      }
      await page.waitForTimeout(500)
      result.ui = await page.locator('body').innerText()
      await page.screenshot({ path: dir + '/final.png' })
      if (id === 'B04') {
        const attachment = result.messages[0].attachments.find((a) => a.kind === 'audio')
        if (attachment) {
          const response = await context.request.get(state.origin + attachment.url)
          const data = await response.body()
          const file = dir + '/actual-recording.webm'
          writeFileSync(file, data)
          result.recording = {
            attachment,
            file,
            status: response.status(),
            bytes: data.length,
            sha256: createHash('sha256').update(data).digest('hex'),
          }
        }
      }
    } catch (error) {
      result.error = error.message
      await page.screenshot({ path: dir + '/error.png' })
    } finally {
      result.finishedAt = new Date().toISOString()
      writeFileSync(dir + '/result.json', JSON.stringify(result, null, 2))
      await context.close()
    }
    console.log(JSON.stringify({ id, error: result.error, messages: result.messages.length }))
  }
} finally {
  await browser.close()
}
