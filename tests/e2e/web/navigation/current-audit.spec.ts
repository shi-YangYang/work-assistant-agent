import type { Work } from '@paa/api-contracts'
import { test, expect, login as loginPage } from '../fixtures/test'

test('S68 W06 W07 @cross mobile panels preserve draft, center dialogs, close and retain focus', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login('employee')
  await page.goto(state.origin + '/assistant?new=1')
  for (const viewport of [
    { width: 320, height: 740 },
    { width: 390, height: 844 },
    { width: 430, height: 620 },
  ]) {
    await page.setViewportSize(viewport)
    const editor = page.getByRole('textbox', { name: '工作消息' })
    await editor.fill('待发送草稿')
    await page.getByRole('button', { name: '更多功能', exact: true }).click()
    await expect(page.getByText('适用于所有会话', { exact: true })).toHaveCount(0)
    for (const [trigger, title] of [
      [/^上下文使用情况/, '上下文使用情况'],
      [/^思考强度：/, '思考强度'],
      [/^执行权限：/, '执行权限'],
    ] as const) {
      const button = page.getByRole('button', { name: trigger })
      await button.focus()
      await button.press('Enter')
      const modal = page.getByRole('dialog', { name: title, exact: true })
      await expect(modal).toBeVisible()
      const rect = await modal.boundingBox()
      expect(rect!.x).toBeGreaterThanOrEqual(8)
      expect(rect!.y).toBeGreaterThanOrEqual(8)
      expect(rect!.x + rect!.width).toBeLessThanOrEqual(viewport.width - 8)
      expect(rect!.y + rect!.height).toBeLessThanOrEqual(viewport.height - 8)
      expect(Math.abs(rect!.y + rect!.height / 2 - viewport.height / 2)).toBeLessThan(20)
      await capture(`${viewport.width}-${title}`)
      await page.keyboard.press('Escape')
      await expect(modal).toHaveCount(0)
      await expect(button).toBeFocused()
      await expect(editor).toHaveValue('待发送草稿')
    }
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: '更多功能' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  }
})

test('S68 W19 W20 @cross announcement publish read and delete have real account-specific state', async ({
  page,
  browser,
  state,
  login,
  http,
  capture,
}) => {
  await login()
  const title = `S68公告交互-${Date.now()}`
  await page.goto(state.origin + '/announcement-management/new')
  await page.getByLabel('公告标题').fill(title)
  await page.getByRole('textbox', { name: '公告正文' }).fill('仅用于验收的 **合成公告**。')
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page).toHaveURL(/\/announcement-management\/[a-f0-9]{8}-[a-f0-9-]+$/)
  const id = new URL(page.url()).pathname.split('/').at(-1)!
  const context = await browser.newContext()
  const employee = await context.newPage()
  try {
    await loginPage(employee, state, 'employee')
    await employee.goto(state.origin + '/notifications?tab=announcements')
    const row = employee
      .locator('div')
      .filter({ has: employee.getByRole('link', { name: new RegExp(title) }) })
      .filter({ has: employee.getByRole('button', { name: '标为已读', exact: true }) })
      .last()
    await row.getByRole('button', { name: '标为已读', exact: true }).click()
    await expect(row.getByRole('button', { name: '标为已读' })).toHaveCount(0)
    await employee.reload()
    const ownRead = await employee.request.get(state.origin + `/api/v1/announcements/${id}`)
    expect((await ownRead.json()).unread).toBe(false)
    const adminRead = await http<{ unread: boolean }>(`/api/v1/announcements/${id}`)
    expect(adminRead.data.unread).toBe(true)
    await page.goto(state.origin + '/announcement-management')
    const adminRow = page
      .locator('div')
      .filter({ has: page.getByRole('link', { name: new RegExp(title) }) })
      .filter({ has: page.getByRole('button', { name: '删除', exact: true }) })
      .last()
    let nativeDialogs = 0
    page.on('dialog', async (dialog) => {
      nativeDialogs++
      await dialog.dismiss()
    })
    await adminRow.getByRole('button', { name: '删除', exact: true }).click()
    const confirm = page.getByRole('dialog', { name: '删除公告', exact: true })
    await expect(confirm).toBeVisible()
    await capture('announcement-delete-confirm')
    await confirm.getByRole('button', { name: '取消', exact: true }).click()
    await expect(adminRow).toBeVisible()
    await adminRow.getByRole('button', { name: '删除', exact: true }).click()
    await confirm.getByRole('button', { name: '删除', exact: true }).click()
    await expect(page.getByRole('link', { name: new RegExp(title) })).toHaveCount(0)
    expect(nativeDialogs).toBe(0)
    expect(
      (await employee.request.get(state.origin + `/api/v1/announcements/${id}`)).status(),
    ).toBe(404)
  } finally {
    await context.close()
  }
})

test('S68 W15 @cross checklist toggle persists exactly one item and preserves body', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login('employee')
  const body = {
    schemaVersion: 1,
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: '正文必须保留' }] },
      {
        type: 'taskList',
        content: ['核对数量', '测试启动', '整理记录'].map((text) => ({
          type: 'taskItem',
          attrs: { checked: false },
          content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
        })),
      },
    ],
  }
  const created = await http<Work>('/api/v1/work-items', 'POST', { title: 'S68清单交互', body })
  expect(created.status).toBe(201)
  await page.goto(state.origin + '/work/' + created.data.id)
  const checks = page.getByRole('checkbox')
  await expect(checks).toHaveCount(3)
  await checks.nth(1).click()
  await expect(checks.nth(1)).toBeChecked()
  await expect(checks.nth(0)).not.toBeChecked()
  await page.reload()
  await expect(checks.nth(1)).toBeChecked()
  const stored = await http<Work>('/api/v1/work-items/' + created.data.id)
  expect(stored.data.revision).toBe(created.data.revision + 1)
  expect(stored.data.bodyText).toContain('正文必须保留')
  expect(stored.data.title).toBe(created.data.title)
  await page.setViewportSize({ width: 390, height: 844 })
  await capture('checklist-persisted-mobile')
})
