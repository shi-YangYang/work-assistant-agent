import type { Page } from '@playwright/test'
import type { Work } from '@paa/api-contracts'
import { test, expect } from '../fixtures/test'

async function theme(page: Page, name: '浅色' | '深色' | '跟随系统') {
  await page.getByRole('button', { name: 'Noria 外观' }).click()
  const dialog = page.getByRole('dialog', { name: 'Noria 外观' })
  await dialog.getByRole('button', { name, exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Noria 外观' })).toBeFocused()
}

const pages = [
  ['/assistant', ''],
  ['/work', '我的工作'],
  ['/team', '团队看板'],
  ['/members', '成员管理'],
  ['/settings/account', '账户'],
  ['/settings/appearance', '外观'],
  ['/settings/rules', '汇报规则'],
  ['/settings/support', '问题反馈'],
  ['/settings/models', '模型服务管理'],
  ['/settings/usage', '模型用量'],
  ['/settings/voiceprints', '公司声纹'],
  ['/settings/login', '登录方式'],
]

for (const [path, heading] of pages) {
  test(`W03 page ${path}`, async ({ page, state, login, capture }) => {
    await login()
    await page.goto(state.origin + path)
    if (heading)
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
    else await expect(page.getByRole('textbox', { name: '工作消息' })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByRole('navigation', { name: '面包屑' })).toHaveCount(0)
    const pet = page.getByRole('button', { name: 'Noria 外观' })
    const center = await pet.evaluate((node) => {
      const bounds = node.getBoundingClientRect()
      const main = node.closest('section')!.getBoundingClientRect()
      return Math.abs(bounds.x + bounds.width / 2 - main.x - main.width / 2)
    })
    expect(center).toBeLessThanOrEqual(1)
    await capture('desktop-light')
    await theme(page, '深色')
    await capture('desktop-dark')
    await page.setViewportSize({ width: 390, height: 844 })
    await capture('mobile-dark')
    await page.setViewportSize({ width: 360, height: 780 })
    await theme(page, '浅色')
    if (heading)
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
    await capture('mobile-light')
    await page.getByRole('button', { name: '展开导航', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '导航', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: '导航', exact: true })).toHaveCount(0)
  })
}

test('W03 @cross employee navigation, reports and role restricted deep links', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login('employee')
  for (const path of [
    '/members',
    '/settings/models',
    '/settings/voiceprints',
    '/settings/login',
    '/team',
  ]) {
    await page.goto(state.origin + path)
    await expect(page.getByRole('navigation', { name: '工作空间' })).toBeAttached()
    await expect(
      page.getByRole('heading', { name: /成员管理|模型服务管理|公司声纹|登录方式|团队看板/ }),
    ).toHaveCount(0)
  }
  await page.goto(state.origin + '/reports')
  await expect(page.getByRole('heading', { name: '我的报告', exact: true })).toBeVisible()
  await capture('employee-reports-empty')
  await theme(page, '深色')
  await capture('employee-reports-desktop-dark')
  await page.setViewportSize({ width: 390, height: 844 })
  await capture('employee-reports-mobile-dark')
  await page.setViewportSize({ width: 360, height: 780 })
  await theme(page, '浅色')
  await capture('employee-reports-mobile-light')
  await page.getByRole('button', { name: '全部报告', exact: true }).click()
  await page.getByRole('button', { name: '周报', exact: true }).click()
  await expect(page.getByRole('button', { name: '生成周报', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '汇报安排', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await capture('employee-reports-weekly')
})

test('W03 pet appearance preserves assistant and work drafts, navigation identity, and request counts', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login()
  await page.goto(state.origin + '/assistant?new=1')
  const composer = page.getByRole('textbox', { name: '工作消息' })
  await composer.fill('保留这条尚未发送的消息')
  const pet = page.getByRole('button', { name: 'Noria 外观' })
  await pet.evaluate((node) => node.setAttribute('data-stability-check', 'same-pet'))
  const requests: string[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/v1/')) requests.push(request.url())
  })
  await theme(page, '深色')
  await expect(composer).toHaveValue('保留这条尚未发送的消息')
  expect(requests).toEqual([])
  await page.keyboard.press('ControlOrMeta+k')
  await expect(page.getByRole('dialog', { name: '查找页面与操作' })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Noria 外观' }).click()
  await capture('appearance-dialog-dark')
  await page.keyboard.press('Escape')
  await page.getByRole('link', { name: '我的工作', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的工作', exact: true })).toBeVisible()
  await expect(pet).toHaveAttribute('data-stability-check', 'same-pet')
  await expect(pet.locator('[data-animate]')).toHaveAttribute('data-animate', 'false')
  await page.getByRole('link', { name: '工作助手', exact: true }).click()
  await expect(composer).toHaveValue('保留这条尚未发送的消息')
  const created = await http<Work>('/api/v1/work-items', 'POST', { title: '外观切换草稿验证' })
  await page.goto(state.origin + '/work/' + created.data.id)
  await page.getByRole('button', { name: '编辑内容' }).click()
  const editor = page.getByRole('textbox', { name: '工作正文' })
  await editor.fill('尚未保存的工作正文')
  await theme(page, '浅色')
  await expect(editor).toHaveText('尚未保存的工作正文')
  await page.setViewportSize({ width: 360, height: 780 })
  await page.getByRole('button', { name: 'Noria 外观' }).click()
  await capture('appearance-dialog-mobile')
})

test('W03 details and source retain contextual returns, history has no duplicate back link', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login('employee')
  const title = `返回入口验证-${Date.now()}`
  const created = await http<Work>('/api/v1/work-items', 'POST', { title })
  await page.goto(state.origin + '/work?q=' + encodeURIComponent(title))
  await page.getByRole('link', { name: new RegExp(title) }).click()
  await expect(page.getByRole('link', { name: '返回我的工作' })).toBeVisible()
  await capture('work-detail-light')
  await theme(page, '深色')
  await capture('work-detail-dark')
  await page.getByRole('link', { name: '查看此版本' }).first().click()
  await expect(page.getByRole('link', { name: /返回最新版本|返回上一步/ })).toHaveCount(1)
  await expect(page.getByRole('link', { name: '返回我的工作' })).toHaveCount(0)
  await capture('work-history-dark')
  await page.getByRole('link', { name: /返回最新版本|返回上一步/ }).click()
  await page.getByRole('link', { name: '返回我的工作' }).click()
  await expect(page).toHaveURL(/\/work(?:\?q=)?/)
  await page.goto(state.origin + '/messages/missing-source')
  await expect(page.getByRole('link', { name: '返回工作助手' })).toBeVisible()
  await expect(page.getByRole('alert')).toBeVisible()
  await capture('source-error-dark')
  await page.getByRole('link', { name: '返回工作助手' }).click()
  await expect(page.getByRole('textbox', { name: '工作消息' })).toBeVisible()
  // Missing records retain a safe direct-entry return before loading succeeds.
  await page.goto(state.origin + '/reports/missing-report')
  await expect(page.getByRole('link', { name: '返回我的报告' })).toBeVisible()
  await page.getByRole('link', { name: '返回我的报告' }).click()
  await expect(page.getByRole('heading', { name: '我的报告', exact: true })).toBeVisible()
  expect(created.status).toBe(201)
})

test('W03 employee notification, report and message source retain local navigation on small screens', async ({
  page,
  state,
  login,
  capture,
}) => {
  const ownerId = state.users.employee.id
  const report = {
    id: 'pet-report',
    ownerId,
    kind: 'daily',
    period: '2026-10-05',
    periodEnd: '2026-10-05',
    timezone: 'Asia/Shanghai',
    revision: 1,
    publishedRevision: 0,
    content: {
      completed: '完成客户需求梳理',
      ongoing: '准备下一步方案',
      blockers: '',
      next: '确认方案范围',
    },
    revisions: [],
    updatedAt: '2026-10-05T08:00:00Z',
  }
  const source = {
    id: 'pet-source',
    ownerId,
    conversationId: 'pet-chat',
    text: '这是一条可回溯的原始工作记录。',
    reply: '已记录客户需求。',
    createdAt: '2026-10-05T08:00:00Z',
    attachments: [],
    drafts: [],
    suggestions: [],
  }
  let read = false
  await page.route('**/api/v1/notifications?*', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'pet-notification',
            stage: 'ready',
            read,
            obligation: {
              id: 'pet-obligation',
              kind: 'daily',
              period: report.period,
              periodEnd: report.periodEnd,
              timezone: report.timezone,
              deadlineAt: '2026-10-05T12:00:00Z',
              reportId: report.id,
            },
          },
        ],
        unread: read ? 0 : 1,
        nextCursor: null,
      },
    }),
  )
  await page.route('**/api/v1/notifications/pet-notification/read', (route) => {
    read = true
    return route.fulfill({ json: {} })
  })
  await page.route('**/api/v1/reports/pet-report', (route) => route.fulfill({ json: report }))
  await page.route('**/api/v1/reports/pet-report/sources?*', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'source-link',
            workId: 'fixture-work',
            workDeleted: true,
            title: '客户需求',
            revision: 1,
            sourceIds: ['pet-source'],
          },
        ],
      },
    }),
  )
  await page.route('**/api/v1/messages/pet-source', (route) => route.fulfill({ json: source }))
  await page.route('**/api/v1/conversations/pet-chat', (route) =>
    route.fulfill({ json: { id: 'pet-chat', title: '客户需求', revision: 1, personaId: 'noria' } }),
  )
  await page.route('**/api/v1/messages?conversationId=pet-chat', (route) =>
    route.fulfill({ json: { items: [source], nextCursor: null } }),
  )
  for (const suffix of ['active-job', 'interactions', 'context-usage'])
    await page.route(`**/api/v1/conversations/pet-chat/${suffix}`, (route) =>
      route.fulfill({
        json:
          suffix === 'active-job'
            ? { job: null }
            : suffix === 'context-usage'
              ? { contextUsage: null }
              : { items: [] },
      }),
    )
  await page.route('**/api/v1/business-actions?conversationId=pet-chat*', (route) =>
    route.fulfill({ json: { items: [], nextCursor: null } }),
  )
  await login('employee')
  await page.setViewportSize({ width: 360, height: 780 })
  await page.getByRole('button', { name: '展开导航', exact: true }).click()
  await page.getByRole('button', { name: '汇报通知，1 条未读' }).click()
  await expect(page.getByRole('dialog', { name: '汇报通知', exact: true })).toBeVisible()
  await capture('employee-notifications-mobile')
  await page.getByRole('button', { name: /日报 · 草稿已就绪/ }).click()
  await expect(page).toHaveURL(/\/reports\/pet-report$/)
  expect(read).toBe(true)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '返回我的报告' })).toBeVisible()
  await capture('report-detail-mobile-light')
  await theme(page, '深色')
  await capture('report-detail-mobile-dark')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await capture('report-detail-desktop-dark')
  await theme(page, '浅色')
  await capture('report-detail-desktop-light')
  await page.getByText('工作依据', { exact: true }).click()
  await page.getByRole('link', { name: '原始上报', exact: true }).click()
  await expect(page.getByRole('link', { name: '返回报告详情' })).toBeVisible()
  await capture('message-source-desktop-light')
  await page.getByRole('link', { name: '返回报告详情' }).click()
  await expect(page).toHaveURL(/\/reports\/pet-report$/)
  await page.goto(state.origin + '/messages/pet-source')
  await expect(page.getByRole('link', { name: '返回会话' })).toBeVisible()
  await page.getByRole('link', { name: '返回会话' }).click()
  await expect(page.getByRole('heading', { name: '客户需求', exact: true })).toBeVisible()
  await expect(page.getByText(source.text, { exact: true })).toBeVisible()
  await capture('existing-conversation-desktop-light')
})

test('W03 floating pet leaves page headers and controls reachable at narrow widths', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login()
  const work = await http<Work>('/api/v1/work-items', 'POST', {
    title: '悬浮入口与长工作内容',
    summary: Array.from({ length: 60 }, (_, i) => `第 ${i + 1} 段：内容应从宠物下方滚动。`).join(
      '\n',
    ),
  })
  const failures: string[] = []
  const layoutPages = pages.filter(([path]) =>
    [
      '/assistant',
      '/work',
      '/team',
      '/settings/account',
      '/settings/appearance',
      '/settings/voiceprints',
    ].includes(path),
  )
  for (const width of [1440, 390, 360]) {
    await page.setViewportSize({ width, height: width > 760 ? 1000 : 844 })
    for (const [path, heading] of [...layoutPages, ['/work/' + work.data.id, work.data.title]]) {
      await page.goto(state.origin + path)
      if (heading)
        await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
      else await expect(page.getByRole('textbox', { name: '工作消息' })).toBeVisible()
      const result = await page.getByRole('button', { name: 'Noria 外观' }).evaluate((pet) => {
        const bounds = pet.getBoundingClientRect()
        const stage = pet.parentElement!
        const main = stage.parentElement!
        const mainBounds = main.getBoundingClientRect()
        const intersects = (a: DOMRect, b: DOMRect) =>
          a.width > 0 &&
          a.height > 0 &&
          a.left < b.right &&
          a.right > b.left &&
          a.top < b.bottom &&
          a.bottom > b.top
        const nav = stage.querySelector('button')!
        const navBounds = nav.getBoundingClientRect()
        const covered = [...main.querySelectorAll('button, input, select, a, h2, p')]
          .filter((node) => {
            if (stage.contains(node)) return false
            if (
              node.tagName === 'P' &&
              !node.closest('header') &&
              !node.parentElement?.querySelector(':scope > h2')
            )
              return false
            let rect = node.getBoundingClientRect()
            if (node.tagName === 'H2' || node.tagName === 'P') {
              const range = document.createRange()
              range.selectNodeContents(node)
              const text = range.getBoundingClientRect()
              rect =
                getComputedStyle(node).overflow === 'hidden'
                  ? new DOMRect(
                      Math.max(rect.left, text.left),
                      Math.max(rect.top, text.top),
                      Math.min(rect.right, text.right) - Math.max(rect.left, text.left),
                      Math.min(rect.bottom, text.bottom) - Math.max(rect.top, text.top),
                    )
                  : text
            }
            return intersects(rect, bounds) || intersects(rect, navBounds)
          })
          .map((node) => node.getAttribute('aria-label') || node.textContent?.trim())
        const outside = document.elementFromPoint(bounds.left - 8, bounds.top + 20)
        const content =
          main.querySelector('[data-scroll-container]') ??
          main.querySelector('header')?.parentElement
        return {
          covered,
          center: Math.abs(bounds.left + bounds.width / 2 - mainBounds.left - mainBounds.width / 2),
          stageHeight: stage.getBoundingClientRect().height,
          contentTop: content?.getBoundingClientRect().top,
          mainTop: mainBounds.top,
          outsideReachesContent: !stage.contains(outside),
        }
      })
      if (result.covered.length) failures.push(`${width} ${path}: ${result.covered.join(', ')}`)
      expect(result.center, `${width} ${path} centered in content`).toBeLessThanOrEqual(1)
      expect(result.stageHeight, 'floating controls do not consume a row').toBe(0)
      expect(result.contentTop, 'page keeps its original top edge').toBe(result.mainTop)
      expect(result.outsideReachesContent, 'outside avatar hit area reaches page').toBe(true)
      await capture(`overlay-${width}-${path.replaceAll('/', '-')}`)
    }
    await page.goto(state.origin + '/assistant?new=1')
    await expect(page.getByRole('textbox', { name: '工作消息' })).toBeVisible()
    if (width < 760) {
      await page.getByRole('button', { name: '选择人设：Noria人设' }).click()
      await expect(page.getByRole('menu')).toBeVisible()
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: '会话列表', exact: true }).click()
      await expect(page.getByRole('textbox', { name: '搜索会话' })).toBeVisible()
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: '新会话', exact: true }).click()
      await page.getByRole('button', { name: '展开导航', exact: true }).click()
      await expect(page.getByRole('dialog', { name: '导航', exact: true })).toBeVisible()
      await page.keyboard.press('Escape')
    }
    await theme(page, width === 390 ? '深色' : '浅色')
  }
  await page.goto(state.origin + '/work/' + work.data.id)
  await expect(page.getByRole('heading', { name: work.data.title })).toBeVisible()
  const pet = page.getByRole('button', { name: 'Noria 外观' })
  const before = await pet.boundingBox()
  const scroller = page.locator('[data-scroll-container]')
  await scroller.evaluate((node) => node.scrollTo(0, node.scrollHeight))
  expect(await scroller.evaluate((node) => node.scrollTop)).toBeGreaterThan(0)
  expect(await pet.boundingBox()).toEqual(before)
  await capture('overlay-mobile-scrolled')
  expect(failures, 'pet and mobile navigation do not cover initial headings or controls').toEqual(
    [],
  )
})
