import { chromium, expect } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { isolatedEnvironment } from '../../../../tests/e2e/web/fixtures/environment.mjs'
const state = isolatedEnvironment()
if (!process.env.SPEC068_OUTPUT) throw Error('Output required')
const out = resolve(process.env.SPEC068_OUTPUT)
await mkdir(out, { recursive: true })
const source = JSON.parse(
  await readFile(
    'artifacts/spec068/20261013-0fd76fe/browser/real-owned/B68-08/result.json',
    'utf8',
  ),
).turns[0].message
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
await context.addInitScript(() => {
  class ControlledSource extends EventTarget {
    close() {}
  }
  window.EventSource = ControlledSource
})
const page = await context.newPage()
const results = []
try {
  await page.goto(state.origin)
  await page.getByRole('button', { name: /直接登录/ }).click()
  await page.getByLabel('账号', { exact: true }).fill(state.users.realAdmin.username)
  await page.getByLabel('密码', { exact: true }).fill(state.users.realAdmin.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page
    .getByRole('navigation', { name: '工作空间', includeHidden: true })
    .waitFor({ state: 'attached' })
  let current = source
  await page.route('**/api/v1/messages?*', (r) =>
    r.fulfill({ json: { items: [current], nextCursor: null } }),
  )
  await page.route('**/api/v1/messages/' + source.id, (r) => r.fulfill({ json: current }))
  await page.route('**/api/v1/conversations/*/active-job', (r) =>
    r.fulfill({ json: { job: current.job.state === 'running' ? current.job : null } }),
  )
  await page.route('**/api/v1/jobs/' + source.job.id + '/events*', (r) =>
    r.fulfill({ contentType: 'text/event-stream', body: ': controlled image fixture\n\n' }),
  )
  await page.route('**/api/v1/jobs/' + source.job.id, (r) => r.fulfill({ json: current.job }))
  for (const stage of ['generating', 'cancelled', 'failed']) {
    current = structuredClone(source)
    current.reply = ''
    current.deliverables = []
    current.job.state = stage === 'generating' ? 'running' : stage
    current.job.phase = stage === 'generating' ? 'executing' : 'complete'
    current.job.stage = current.job.phase
    current.job.nodes = [
      {
        id: 'controlled-image',
        label: '生成图片',
        kind: 'tool',
        state: stage === 'generating' ? 'running' : stage,
        presentation: { type: 'operation' },
      },
    ]
    current.job.imageGeneration = [1, 2, 3, 4].map((n) => ({
      operation: n,
      state: stage === 'generating' ? (n === 1 ? 'generating' : 'queued') : stage,
      width: 2048,
      height: 2048,
    }))
    await page.goto(state.origin + '/assistant/' + source.conversationId)
    const gallery = page.getByRole('list', { name: '生成图片' })
    await expect(gallery.locator(':scope > li')).toHaveCount(4)
    await gallery.scrollIntoViewIfNeeded()
    const row = {
      stage,
      source: 'controlled API fixture (no model success claim)',
      text: await gallery.innerText(),
      cards: await gallery.locator(':scope > li').evaluateAll((nodes) =>
        nodes.map((n) => ({
          text: n.textContent,
          canvas: !!n.querySelector('canvas'),
          svg: !!n.querySelector('svg'),
          bounds: n.getBoundingClientRect().toJSON(),
        })),
      ),
    }
    for (const theme of ['light', 'dark']) {
      await page.evaluate((value) => {
        localStorage.setItem('paa.company.theme', value)
      }, theme)
      await page.reload()
      await gallery.waitFor()
      await gallery.scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(out, stage + '-' + theme + '.png') })
    }
    results.push(row)
  }
  current = structuredClone(source)
  let release
  const heldImages = new Promise((resolve) => {
    release = resolve
  })
  for (const deliverable of source.deliverables) {
    for (const file of deliverable.files) {
      await page.route('**' + file.url, async (route) => {
        await heldImages
        await route.continue().catch(() => {})
      })
    }
  }
  await page.goto(state.origin + '/assistant/' + source.conversationId)
  const loadingGallery = page.getByRole('list', { name: '生成图片' })
  await expect(loadingGallery.locator(':scope > li')).toHaveCount(4)
  await loadingGallery.scrollIntoViewIfNeeded()
  await page.screenshot({ path: resolve(out, 'completed-image-loading.png') })
  results.push({
    stage: 'completed-image-loading',
    source: 'real completed message; controlled delayed image bytes',
    text: await loadingGallery.innerText(),
    canvases: await loadingGallery.locator('canvas').count(),
  })
  release()
} finally {
  await writeFile(resolve(out, 'observations.json'), JSON.stringify(results, null, 2))
  await browser.close()
}
