// Narrow actual-page hit testing for the model-strength controls in MUI-004.
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { launch, origin, timestamp } from './assistant-fixture.mjs'
const output = resolve(process.env.REPAIR_OUTPUT || 'artifacts/spec073-fixes/20261017-mui-repair')
const phase = process.env.REPAIR_PHASE || 'after'
await mkdir(output, { recursive: true })
const run = await launch({ role: 'admin' })
const model = {
  id: 'repair-model',
  model: 'synthetic-mobile-model',
  protocol: 'chat',
  protocolMode: 'manual',
  reasoning: { efforts: ['low', 'medium', 'high', 'max', 'ultra', 'extended'], initial: 'high' },
  parameters: {},
  streaming: true,
  language: '',
}
try {
  await run.page.route('**/api/v1/settings/model-services', (route) =>
    route.fulfill({
      json: {
        services: [
          {
            id: 'repair-service',
            name: '合成模型服务',
            baseUrl: 'https://example.invalid/v1',
            models: [model],
            revision: 1,
            hasKey: true,
            updatedAt: timestamp,
          },
        ],
        routing: {
          revision: 1,
          source: 'database',
          assistant: null,
          report: 'follow',
          asr: null,
          image: null,
          environment: null,
        },
      },
    }),
  )
  await run.page.goto(origin + '/settings/models')
  await run.page.getByRole('button', { name: '设置 synthetic-mobile-model', exact: true }).click()
  await run.page.getByRole('button', { name: '删除强度 low', exact: true }).scrollIntoViewIfNeeded()
  await run.page.waitForTimeout(450)
  const controls = await run.page.evaluate(() =>
    [...document.querySelectorAll('button')]
      .filter((b) => /^删除强度/.test(b.getAttribute('aria-label') || ''))
      .map((b) => {
        const r = b.getBoundingClientRect(),
          cx = r.x + r.width / 2,
          cy = r.y + r.height / 2
        const hit = (x, y) => {
          const e = document.elementFromPoint(x, y)
          return e === b || b.contains(e)
        }
        let xhits = 0,
          yhits = 0
        for (let n = -64; n <= 64; n++) {
          if (hit(cx + n, cy)) xhits++
          if (hit(cx, cy + n)) yhits++
        }
        return {
          name: b.getAttribute('aria-label'),
          rect: r.toJSON(),
          horizontalHitPx: xhits,
          verticalHitPx: yhits,
        }
      }),
  )
  const overlaps = []
  for (let i = 0; i < controls.length; i++)
    for (let j = i + 1; j < controls.length; j++) {
      const a = controls[i].rect,
        b = controls[j].rect
      if (
        Math.min(a.right, b.right) > Math.max(a.left, b.left) &&
        Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top)
      )
        overlaps.push([controls[i].name, controls[j].name])
    }
  await writeFile(
    resolve(output, `MUI-004-${phase}-tags-geometry.json`),
    JSON.stringify(
      { controls, overlaps, errors: run.s.errors, unhandled: run.s.unhandled },
      null,
      2,
    ),
  )
  await run.page.screenshot({ path: resolve(output, `MUI-004-${phase}-tags.png`) })
  if (
    phase === 'after' &&
    (controls.length !== 6 ||
      controls.some((c) => c.horizontalHitPx < 44 || c.verticalHitPx < 44) ||
      overlaps.length)
  )
    throw new Error('Model-strength controls do not meet actual 44px nonoverlap requirement')
  if (run.s.errors.length || run.s.unhandled.length)
    throw new Error('Fixture had unhandled requests or page errors')
  console.log(
    `MUI004 model strength ${phase}: ${controls.length} controls, ${overlaps.length} overlapping boxes`,
  )
} finally {
  await run.close()
}
