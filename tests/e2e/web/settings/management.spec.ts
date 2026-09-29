import { test, expect } from '../fixtures/test'

test('W15 member lifecycle through real forms', async ({ page, state, login, capture }) => {
  await login()
  await page.goto(state.origin + '/members')
  const name = `浏览器成员-${Date.now()}`
  const username = `ui${Date.now()}`
  async function create() {
    await page.getByRole('button', { name: '添加成员', exact: true }).click()
    const form = page.getByRole('dialog', { name: '添加成员' })
    await form.getByRole('button', { name: '保存', exact: true }).click()
    await expect(form.getByText('请输入姓名')).toBeVisible()
    await form.getByLabel('姓名').fill(name)
    await form.getByLabel('账号').fill(username)
    await form.getByLabel('密码').fill('1111')
    await form.getByRole('button', { name: '保存', exact: true }).click()
    await expect(form).toHaveCount(0)
  }
  await create()
  const row = page
    .locator('div[class*="record-row"]')
    .filter({ has: page.getByRole('heading', { name, exact: true }) })
  await expect(row).toContainText('正常')
  await capture('created-member')
  await row.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '重置密码' }).click()
  const reset = page.getByRole('dialog', { name: `重置 ${name} 的密码` })
  await reset.getByLabel('密码').fill('2222')
  await reset.getByRole('button', { name: '保存', exact: true }).click()
  await expect(reset).toHaveCount(0)
  page.on('dialog', (dialog) => dialog.accept())
  await row.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '停用账号' }).click()
  await expect(row).toContainText('已停用')
  await row.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '启用账号' }).click()
  await expect(row).toContainText('正常')
  await row.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '删除账号' }).click()
  const remove = page.getByRole('dialog', { name: '删除账号' })
  await expect(remove.getByRole('button', { name: '删除账号', exact: true })).toBeEnabled()
  await remove.getByRole('button', { name: '删除账号', exact: true }).click()
  await expect(row).toHaveCount(0)
  await create()
  await expect(row).toContainText('正常')
  await capture('recreated-member')
})

test('W18 employee feedback is handled by administrator', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login('employee')
  const description = `验收反馈-${Date.now()}：上传后需要更明确的状态`
  await page.goto(state.origin + '/settings/support')
  await page.getByLabel('问题描述').fill(description)
  await page.getByRole('button', { name: '提交反馈', exact: true }).click()
  await expect(page.getByLabel('问题描述')).toHaveValue('')
  await page.locator('summary').filter({ hasText: '反馈记录' }).click()
  await expect(page.getByRole('button', { name: new RegExp(description) })).toBeVisible()
  await capture('employee-feedback')
  await page.goto(state.origin + '/settings/account')
  await page.getByRole('button', { name: '退出登录', exact: true }).last().click()
  await login()
  await page.goto(state.origin + '/settings/support')
  await page.locator('summary').filter({ hasText: '反馈记录' }).click()
  await page.getByRole('button', { name: new RegExp(description) }).click()
  const detail = page.getByRole('dialog', { name: '反馈详情' })
  await detail.getByRole('combobox', { name: '状态', exact: true }).selectOption('resolved')
  await detail.getByLabel('处理说明').fill('已核对，测试反馈已处理')
  await detail.getByRole('button', { name: '保存处理结果' }).click()
  await expect(page.getByText('处理结果已保存')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByLabel('处理状态').selectOption('resolved')
  await expect(page.getByRole('button', { name: new RegExp(description) })).toContainText('已处理')
  await capture('handled-feedback')
})

test('W18 report rules save and survive reload', async ({ page, state, login, capture }) => {
  await login()
  await page.goto(state.origin + '/settings/rules')
  await page.getByLabel('公司时区').selectOption('Asia/Shanghai')
  await page.getByLabel('启用汇报安排').first().uncheck()
  await page.getByRole('button', { name: '保存汇报规则' }).click()
  await expect(page.getByText('汇报规则已保存，从后续安排生效')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('公司时区')).toHaveValue('Asia/Shanghai')
  await expect(page.getByLabel('启用汇报安排').first()).not.toBeChecked()
  await capture('saved-rules')
})
