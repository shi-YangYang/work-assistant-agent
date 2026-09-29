import { test, expect } from '../fixtures/test'

test('W12 @cross create edit reference and inspect saved work', async ({
  page,
  state,
  login,
  capture,
  http,
}, info) => {
  const title = `流程验收-${info.project.name}-${Date.now()}`
  await login('employee')
  await page.goto(state.origin + '/work')
  await page.getByRole('button', { name: '新建工作', exact: true }).click()
  const create = page.getByRole('dialog', { name: '新建工作' })
  await create.getByRole('button', { name: '创建工作', exact: true }).click()
  await expect(create).toBeVisible()
  await create.getByLabel('工作事项').fill(title)
  await create.getByLabel('当前进展').fill('已经核对原始客户需求')
  await create.getByLabel('下一步', { exact: true }).fill('制定实施计划')
  await create.getByLabel('截止日期（选填）').fill('2026-10-09')
  await create.getByRole('button', { name: '创建工作', exact: true }).click()
  await expect(create).toHaveCount(0)
  await page.getByRole('link', { name: new RegExp(title) }).click()
  await capture('created')
  await page.getByRole('button', { name: '编辑工作', exact: true }).click()
  const edit = page.getByRole('dialog', { name: '更正工作进展' })
  await edit.getByLabel('当前进展').fill('等待客户确认范围')
  await edit.getByRole('combobox').selectOption('blocked')
  await edit.getByLabel('问题或阻碍').fill('预算待确认')
  await edit.getByRole('button', { name: '保存更正', exact: true }).click()
  await expect(edit).toHaveCount(0)
  await expect(page.getByText('等待客户确认范围', { exact: true }).first()).toBeVisible()
  const saved = await http<{ items: { status: string; blocker: string }[] }>(
    '/api/v1/work-items?q=' + encodeURIComponent(title),
  )
  expect(saved.status).toBe(200)
  expect(saved.data.items).toHaveLength(1)
  expect(saved.data.items[0]).toMatchObject({ status: 'blocked', blocker: '预算待确认' })
  await capture('edited')
  await page.getByRole('button', { name: '让助手协助' }).click()
  await expect(page.getByRole('textbox', { name: '工作消息' })).toBeVisible()
  await expect(page.getByText(title, { exact: true }).last()).toBeVisible()
  await capture('work-reference')
})
