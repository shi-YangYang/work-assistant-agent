import { chromium, expect } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { isolatedEnvironment } from '../../../../tests/e2e/web/fixtures/environment.mjs'
const state = isolatedEnvironment()
if (!process.env.SPEC068_OUTPUT) throw Error('Evidence output required')
const output = resolve(process.env.SPEC068_OUTPUT)
await mkdir(output, { recursive: true })
const rows = []
const browser = await chromium.launch()
async function login(role) {
  const ctx = await browser.newContext({ locale: 'zh-CN' })
  const page = await ctx.newPage()
  await page.goto(state.origin)
  await page.getByRole('button', { name: /直接登录/ }).click()
  await page.getByLabel('账号', { exact: true }).fill(state.users[role].username)
  await page.getByLabel('密码', { exact: true }).fill(state.users[role].password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page
    .getByRole('navigation', { name: '工作空间', includeHidden: true })
    .waitFor({ state: 'attached' })
  return { ctx, page }
}
async function save() {
  await writeFile(resolve(output, 'observations.json'), JSON.stringify(rows, null, 2))
}
try {
  const { ctx, page } = await login('employee')
  const records = JSON.parse(await readFile(process.env.UI_LAYOUT_RECORDS, 'utf8'))
  for (const [label, path] of [
    ['new-click', '/assistant?new=1'],
    ['new', '/assistant?new=1'],
    ['existing', '/assistant/' + records.employee.conversation],
  ]) {
    const previousUrl = page.url()
    if (label === 'new-click')
      await page.getByRole('button', { name: '新会话', exact: true }).click()
    else await page.goto(state.origin + path)
    const box = page.getByRole('textbox', { name: '工作消息' })
    await box.waitFor()
    await box.fill('离线诊断草稿-' + label)
    const row = {
      id: 'offline-' + label,
      previousUrl,
      filled: { url: page.url(), value: await box.inputValue() },
      events: [],
      samples: [],
    }
    const req = (r) => {
      if (new URL(r.url()).pathname.startsWith('/api/v1/'))
        row.events.push({ event: 'request', method: r.method(), path: new URL(r.url()).pathname })
    }
    const fail = (r) =>
      row.events.push({
        event: 'failed',
        method: r.method(),
        path: new URL(r.url()).pathname,
        error: r.failure(),
      })
    page.on('request', req)
    page.on('requestfailed', fail)
    await ctx.setOffline(true)
    await box.press('Enter')
    for (const ms of [50, 250, 1000, 6000]) {
      await page.waitForTimeout(ms)
      row.samples.push({
        ms,
        url: page.url(),
        value: await box.inputValue(),
        alerts: await page.getByRole('alert').allTextContents(),
        body: (await page.locator('body').innerText()).slice(-1200),
      })
    }
    await page.screenshot({ path: resolve(output, label + '-offline.png') })
    await ctx.setOffline(false)
    await page.waitForTimeout(1500)
    row.restored = {
      url: page.url(),
      value: await box.inputValue(),
      alerts: await page.getByRole('alert').allTextContents(),
    }
    await page.screenshot({ path: resolve(output, label + '-restored.png') })
    if (label === 'new-click') {
      await page.goBack()
      await box.waitFor()
      row.previousRoute = { url: page.url(), value: await box.inputValue() }
      await page.goForward()
      await box.waitFor()
      row.newRouteAgain = { url: page.url(), value: await box.inputValue() }
    }
    page.off('request', req)
    page.off('requestfailed', fail)
    rows.push(row)
    await save()
  }
  await ctx.close()
  if (process.env.SPEC068_INSPECT === 'offline') {
    await browser.close()
    process.exit(0)
  }
  const own = await login('realAdmin')
  const p = own.page
  const real = JSON.parse(
    await readFile(
      'artifacts/spec068/20261013-0fd76fe/browser/real-owned/B68-08/result.json',
      'utf8',
    ),
  )
  const turn = real.turns[0]
  await p.goto(state.origin + '/assistant/' + turn.receipt.conversationId)
  const gallery = p.getByRole('list', { name: '生成图片' })
  await expect(gallery.getByRole('img')).toHaveCount(4)
  const imageRow = { id: 'real-image-delivery', files: [], layouts: [] }
  for (const size of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
    { width: 320, height: 620 },
    { width: 768, height: 1024 },
  ]) {
    await p.setViewportSize(size)
    await gallery.scrollIntoViewIfNeeded()
    imageRow.layouts.push({
      size,
      overflow: await p.evaluate(() => document.documentElement.scrollWidth - innerWidth),
      images: await gallery.getByRole('img').evaluateAll((nodes) =>
        nodes.map((n) => {
          const r = n.getBoundingClientRect()
          return { x: r.x, y: r.y, width: r.width, height: r.height, naturalWidth: n.naturalWidth }
        }),
      ),
      entryCount: await p.getByRole('button', { name: '查看生成图片（4张）', exact: true }).count(),
    })
    await p.screenshot({ path: resolve(output, 'images-' + size.width + '.png') })
  }
  await p.setViewportSize({ width: 390, height: 844 })
  await gallery.getByRole('button', { name: /^预览/ }).first().click()
  const modal = p.getByRole('dialog')
  await expect(modal).toBeVisible()
  await p.screenshot({ path: resolve(output, 'image-preview-mobile.png') })
  const downloadPromise = p.waitForEvent('download')
  await modal.getByRole('button', { name: /下载/ }).click()
  const download = await downloadPromise
  await download.saveAs(resolve(output, 'image-ui-download.png'))
  imageRow.download = { name: download.suggestedFilename(), failure: await download.failure() }
  await p.keyboard.press('Escape')
  for (const d of turn.message.deliverables) {
    const f = d.files[0]
    const b = await p.evaluate(async (url) => {
      const r = await fetch(url)
      return { status: r.status, bytes: Array.from(new Uint8Array(await r.arrayBuffer())) }
    }, f.url)
    const data = Buffer.from(b.bytes)
    imageRow.files.push({
      id: f.id,
      status: b.status,
      size: data.length,
      sha256: createHash('sha256').update(data).digest('hex'),
      png: data.subarray(0, 8).toString('hex'),
    })
  }
  rows.push(imageRow)
  await save()
  await own.ctx.close()
  const usage = await login('admin')
  await usage.page.goto(state.origin + '/settings/usage')
  await usage.page.locator('table tbody tr').first().waitFor()
  const region = usage.page.getByRole('region', { name: '模型调用记录' })
  const u = { id: 'usage-scroll', samples: [] }
  for (const w of [360, 390]) {
    await usage.page.setViewportSize({ width: w, height: 844 })
    await region.evaluate((n) => n.scrollTo({ left: 0, behavior: 'instant' }))
    await usage.page.waitForTimeout(500)
    u.samples.push(
      await region.evaluate((n) => ({
        viewport: innerWidth,
        width: n.clientWidth,
        scrollWidth: n.scrollWidth,
        left: n.scrollLeft,
        attrs: [n.dataset.scrollLeft, n.dataset.scrollRight],
        hint: n.previousElementSibling?.textContent,
      })),
    )
    await usage.page.screenshot({ path: resolve(output, 'usage-' + w + '.png') })
    await region.focus()
    await usage.page.keyboard.press('ArrowRight')
    await usage.page.waitForTimeout(100)
    u.samples.push(
      await region.evaluate((n) => ({
        afterKey: true,
        left: n.scrollLeft,
        attrs: [n.dataset.scrollLeft, n.dataset.scrollRight],
      })),
    )
  }
  rows.push(u)
  await save()
  await usage.ctx.close()
} finally {
  await browser.close()
  await save()
}
