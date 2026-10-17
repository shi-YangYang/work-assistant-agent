// Eight paired actual-app screenshots. Every business API is intercepted; unknown calls fail closed.
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import {
  launch,
  origin,
  message,
  attachment,
  wav,
  timestamp,
  expect,
} from './assistant-fixture.mjs'

const phase = process.env.REPAIR_PHASE || 'before'
const output = resolve(process.env.REPAIR_OUTPUT || 'artifacts/spec073-fixes/20261017-mui-repair')
await mkdir(output, { recursive: true })
const ids = (process.env.REPAIR_ISSUES || '001,002,003,004,005,006,007,008').split(',')
const index = JSON.parse(
  await readFile(resolve(output, `screenshot-index-${phase}.json`), 'utf8').catch(() => '[]'),
).filter((item) => !ids.includes(item.id.slice(-3)))
const work = {
  id: 'repair-work',
  ownerId: 'audit-owner',
  title: '移动端资料整理与协作计划',
  status: 'in_progress',
  summary: '核对材料，整理下一步安排。',
  bodyText: '核对材料，整理下一步安排。',
  body: {
    schemaVersion: 1,
    content: [
      {
        type: 'paragraph',
        attrs: { id: 'p-1' },
        content: [{ type: 'text', text: '核对材料，整理下一步安排。' }],
      },
    ],
  },
  revision: 1,
  updatedAt: timestamp,
  dueDate: '2026-10-23',
  blocker: '',
  nextStep: '完成资料核对',
  sourceIds: [],
  materialIds: ['m1', 'm2', 'm3', 'm4', 'm5'],
  history: [],
}
const names = [
  '会议纪要.md',
  '参考资料.txt',
  '下周工作计划.md',
  '超长中文文件名用于核对全部附件弹窗中的文字换行和文件大小操作位置完整保留.md',
  'VeryLongFilenameWithoutAnySpacesForCheckingMaterialDialogContentWidthAndFileSizePlacement.txt',
]
const materials = names.map((name, i) => ({
  id: 'm' + (i + 1),
  workId: work.id,
  revision: 1,
  attachment: attachment('document', 'doc' + i, name),
  createdAt: timestamp,
  removed: false,
}))
const member = {
  id: 'audit-owner',
  name: '手机审计用户',
  username: 'ui-audit',
  role: 'employee',
  active: true,
  hasPassword: true,
}
const memory = {
  enabled: true,
  revision: 1,
  markdown: '# 沟通偏好\n\n优先给出结论，再说明需要核对的材料。',
  updatedAt: timestamp,
  maxCharacters: 12000,
}

async function ready(page) {
  await page.waitForLoadState('domcontentloaded')
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(450)
}
async function extras(run) {
  run.s.referenceWorks = [work]
  await run.page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.slice(7)
    let data
    if (path === '/assistant/memory') data = memory
    else if (path === '/team/workspace/work')
      data = {
        items: [{ id: work.id, member, work }],
        nextCursor: null,
        total: 1,
        counts: { all: 1, in_progress: 1, blocked: 0, done: 0 },
        members: [member],
        range: { start: '2026-10-12', end: '2026-10-18', timezone: 'Asia/Shanghai' },
      }
    else if (path === '/work-items/repair-work/materials')
      data = { items: materials, nextCursor: null }
    else if (path.startsWith('/work-items/repair-work/materials/'))
      data = materials.find((m) => m.id === path.split('/').at(-1))
    else if (path === '/work-items/repair-work/updates') data = { items: [], nextCursor: null }
    else return route.fallback()
    run.s.log.push({ path, method: route.request().method(), fixture: 'repair' })
    return route.fulfill({ json: data })
  })
}
async function go(run, path) {
  await run.page.goto(origin + path)
  await ready(run.page)
}
async function shot(run, id, notes = '') {
  const file = `MUI-${id}-${phase}.png`
  await run.page.screenshot({ path: resolve(output, file) })
  const geometry = await run.page.evaluate(() => ({
    viewport: { width: innerWidth, height: innerHeight },
    documentWidth: document.documentElement.scrollWidth,
    controls: [...document.querySelectorAll('button,input,h1')]
      .map((e) => ({
        name: e.getAttribute('aria-label') || e.textContent.trim().slice(0, 70),
        box: e.getBoundingClientRect().toJSON(),
      }))
      .filter((e) => e.box.width && e.box.height && e.box.y >= 0 && e.box.y < innerHeight),
  }))
  index.push({
    id: `MUI-${id}`,
    phase,
    file,
    ...run.env,
    route: new URL(run.page.url()).pathname,
    dataMode: 'controlled actual React app; all API routes intercepted, unknown 501',
    notes,
    geometry,
  })
}
async function touchGeometry(page) {
  const targets = page.getByRole('button', { name: /^(移除|播放.*voice)/ })
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
        for (let n = -64; n <= 64; n++) {
          if (hit(cx + n, cy)) horizontalHitPx++
          if (hit(cx, cy + n)) verticalHitPx++
        }
        const siblings = [...b.closest('[role="region"]').querySelectorAll('button')]
          .filter((other) => other !== b)
          .map((other) => ({
            name: other.getAttribute('aria-label'),
            box: other.getBoundingClientRect(),
          }))
        const overlaps = siblings
          .filter(
            ({ box }) =>
              Math.min(r.right, box.right) > Math.max(r.left, box.left) &&
              Math.min(r.bottom, box.bottom) > Math.max(r.top, box.top),
          )
          .map(({ name }) => name)
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
  await page.getByRole('region', { name: /待发送附件/ }).evaluate((e) => {
    e.scrollLeft = 0
  })
  return controls
}

for (const id of ids) {
  const run = await launch({
    width: ['001', '002'].includes(id) ? 320 : 390,
    height: ['001', '002'].includes(id) ? 568 : 844,
    role: id === '002' ? 'admin' : 'employee',
  })
  run.page.setDefaultTimeout(7000)
  try {
    await extras(run)
    if (id === '001') {
      await go(run, '/work/repair-work')
      await run.page.getByRole('heading', { name: work.title }).waitFor()
      await shot(run, id, 'Work detail, first screen; hidden pet.')
    }
    if (id === '002') {
      await go(run, '/team')
      await run.page.getByText(work.title, { exact: true }).waitFor()
      await shot(run, id, 'Team current-work, filters collapsed.')
    }
    if (id === '003') {
      await go(run, '/work/repair-work')
      await run.page.getByRole('button', { name: '管理工作', exact: true }).click()
      await run.page.getByRole('menuitem', { name: /^全部附件/ }).click()
      await run.page.getByRole('dialog').waitFor()
      await ready(run.page)
      await shot(
        run,
        id,
        'Five identical names/data, including long Chinese and unbroken English filenames.',
      )
    }
    if (['004', '005', '007'].includes(id)) {
      if (id === '007')
        run.s.messages = [
          message({
            text: '请综合这七份材料给出结论。',
            reply: await readFile(resolve(output, `material-${phase}.txt`), 'utf8'),
          }),
        ]
      if (id === '005')
        run.s.messages = [message({ reply: '## 检查结果\n\n文字放大时，功能入口仍应能清晰区分。' })]
      await go(run, '/assistant/audit-chat')
      await run.page.getByRole('textbox', { name: '工作消息' }).waitFor()
      if (id === '004') {
        await run.page
          .locator('input[type=file]')
          .last()
          .setInputFiles([
            { name: '触摸目标.md', mimeType: 'text/markdown', buffer: Buffer.from('test') },
            { name: 'voice.wav', mimeType: 'audio/wav', buffer: wav() },
          ])
        await expect.poll(() => run.s.uploads.size).toBe(2)
        await ready(run.page)
        await writeFile(
          resolve(output, `MUI-004-${phase}-geometry.json`),
          JSON.stringify(await touchGeometry(run.page), null, 2),
        )
      }
      if (id === '005') {
        await run.page
          .getByRole('textbox', { name: '工作消息' })
          .fill('我希望整理全部材料，并保留原文中的重要细节。')
        await run.page.getByRole('button', { name: '更多功能', exact: true }).click()
        await run.page.evaluate(() => {
          const entries = [...document.querySelectorAll('body *')]
            .filter((e) => e instanceof HTMLElement)
            .map((e) => {
              const c = getComputedStyle(e)
              return { e, font: parseFloat(c.fontSize), line: parseFloat(c.lineHeight) }
            })
          for (const { e, font, line } of entries) {
            e.style.fontSize = font * 2 + 'px'
            if (Number.isFinite(line)) e.style.lineHeight = line * 2 + 'px'
          }
        })
      }
      await ready(run.page)
      if (id === '007')
        await run.page
          .getByText('材料覆盖范围', { exact: false })
          .first()
          .scrollIntoViewIfNeeded()
          .catch(() => {})
      await shot(
        run,
        id,
        id === '005'
          ? 'Computed font-size and numeric line-height ×2, normal line-height preserved; not a real-device system font test.'
          : id === '007'
            ? 'Actual server formatter output supplied by backend implementer; same seven complete text materials.'
            : 'File and synthetic audio draft; geometry includes elementFromPoint actual hit sampling.',
      )
    }
    if (id === '006') {
      await go(run, '/work')
      await run.page.getByRole('button', { name: /^展开导航/ }).click()
      await ready(run.page)
      await shot(run, id, 'Hidden pet, two unread notifications, open mobile navigation.')
    }
    if (id === '008') {
      await go(run, '/settings/memory')
      await run.page.getByRole('button', { name: '清空记忆', exact: true }).waitFor()
      if (phase === 'before') {
        await shot(
          run,
          id,
          'Actual page before native confirm. Playwright page screenshots cannot include browser-native dialogs; companion event records exact native confirm message. No synthetic dialog image.',
        )
        const dialogs = []
        run.page.on('dialog', async (d) => {
          dialogs.push({ type: d.type(), message: d.message() })
          await d.dismiss()
        })
        await run.page.getByRole('button', { name: '清空记忆', exact: true }).click()
        await writeFile(
          resolve(output, 'MUI-008-before-dialog-events.json'),
          JSON.stringify(dialogs, null, 2),
        )
      } else {
        await run.page.getByRole('button', { name: '清空记忆', exact: true }).click()
        await run.page.getByRole('dialog').waitFor()
        await ready(run.page)
        await shot(run, id, 'Actual application confirmation dialog for same saved memory.')
      }
    }
    if (run.s.errors.length || run.s.unhandled.length)
      throw new Error(JSON.stringify({ errors: run.s.errors, unhandled: run.s.unhandled }))
    console.log(`Captured MUI-${id} ${phase}`)
  } catch (error) {
    console.error(`MUI-${id}: ${error}`)
    await run.page.screenshot({ path: resolve(output, `MUI-${id}-${phase}-failure.png`) })
    process.exitCode = 1
  } finally {
    await writeFile(
      resolve(output, `MUI-${id}-${phase}-requests.json`),
      JSON.stringify(run.s.log, null, 2),
    )
    await run.close()
    await writeFile(
      resolve(output, `screenshot-index-${phase}.json`),
      JSON.stringify(index, null, 2),
    )
  }
}
