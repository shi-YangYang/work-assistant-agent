// One affected boundary: narrow dark composer with image/document/audio targets and ordinary text.
import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { launch, origin, previewPng, wav, expect } from './assistant-fixture.mjs'
const output = resolve(process.env.REPAIR_OUTPUT || 'artifacts/spec073-fixes/20261017-mui-repair')
const run = await launch({ width: 320, height: 568, theme: 'dark' })
try {
  await run.page.goto(origin + '/assistant/audit-chat')
  await run.page.getByRole('textbox', { name: '工作消息' }).waitFor()
  await run.page
    .locator('input[type=file]')
    .last()
    .setInputFiles([
      { name: '合成图.png', mimeType: 'image/png', buffer: previewPng },
      { name: '参考资料.md', mimeType: 'text/markdown', buffer: Buffer.from('synthetic fixture') },
      { name: 'voice.wav', mimeType: 'audio/wav', buffer: wav() },
    ])
  await expect.poll(() => run.s.uploads.size).toBe(3)
  const region = run.page.getByRole('region', { name: /待发送附件/ })
  const targets = region.getByRole('button', { name: /^(预览|移除|播放)/ })
  const controls = []
  for (let i = 0; i < (await targets.count()); i++) {
    const target = targets.nth(i)
    await target.scrollIntoViewIfNeeded()
    controls.push(
      await target.evaluate((b) => {
        const r = b.getBoundingClientRect(),
          cx = r.x + r.width / 2,
          cy = r.y + r.height / 2
        const hit = (x, y) => {
          const e = document.elementFromPoint(x, y)
          return e === b || b.contains(e)
        }
        let horizontalHitPx = 0,
          verticalHitPx = 0
        for (let n = -80; n <= 80; n++) {
          if (hit(cx + n, cy)) horizontalHitPx++
          if (hit(cx, cy + n)) verticalHitPx++
        }
        const overlaps = [...b.closest('[role="region"]').querySelectorAll('button')]
          .filter((o) => o !== b)
          .filter((o) => {
            const q = o.getBoundingClientRect()
            return (
              Math.min(r.right, q.right) > Math.max(r.left, q.left) &&
              Math.min(r.bottom, q.bottom) > Math.max(r.top, q.top)
            )
          })
          .map((o) => o.getAttribute('aria-label'))
        return {
          name: b.getAttribute('aria-label'),
          rect: r.toJSON(),
          horizontalHitPx,
          verticalHitPx,
          overlaps,
        }
      }),
    )
  }
  await region.evaluate((e) => {
    e.scrollLeft = 0
  })
  await run.page.waitForTimeout(350)
  await run.page.screenshot({ path: resolve(output, 'MUI-004-after-mixed-320-dark.png') })
  await run.page.getByRole('button', { name: '预览合成图.png', exact: true }).click()
  await run.page.getByRole('dialog').waitFor()
  await run.page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
  await run.page.getByRole('button', { name: '更多功能', exact: true }).click()
  await run.page.waitForTimeout(350)
  await run.page.screenshot({ path: resolve(output, 'MUI-005-after-normal-320-dark.png') })
  const result = {
    viewport: { width: 320, height: 568 },
    theme: 'dark',
    controls,
    imagePreviewOpenedAndClosed: true,
    pageErrors: run.s.errors,
    unhandled: run.s.unhandled,
  }
  await writeFile(
    resolve(output, 'MUI-004-after-mixed-320-dark-geometry.json'),
    JSON.stringify(result, null, 2),
  )
  if (
    controls.length !== 6 ||
    controls.some((c) => c.horizontalHitPx < 44 || c.verticalHitPx < 44 || c.overlaps.length)
  )
    throw new Error('Affected mixed attachment target is below 44px or overlaps another control')
  if (run.s.errors.length || run.s.unhandled.length) throw new Error('Unhandled API or page error')
  console.log(
    '320px dark mixed attachments: all 6 preview/delete/play targets >=44px, no overlaps; image preview opens/closes.',
  )
} finally {
  await run.close()
}
