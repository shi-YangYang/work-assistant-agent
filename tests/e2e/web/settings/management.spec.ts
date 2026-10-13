import { test, expect } from '../fixtures/test'

test('W15 member lifecycle through real forms', async ({ page, state, login, capture }) => {
  await login()
  await page.goto(state.origin + '/members')
  const name = `浏览器成员-${Date.now()}`
  const renamed = `${name}-更正姓名`
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
  const row = page.getByRole('row').filter({ has: page.getByText(username, { exact: true }) })
  await create()
  await expect(row).toBeVisible()
  await page.getByRole('textbox', { name: '搜索成员' }).fill(username.toUpperCase())
  await expect(page.getByText(/找到 1 人，共/)).toBeVisible()
  await page.reload()
  await expect(row).toBeVisible()
  await expect(page.getByRole('textbox', { name: '搜索成员' })).toHaveValue(username.toUpperCase())
  await capture('created-member')
  await row.getByRole('button', { name: '更多操作' }).click()
  await expect(page.getByRole('menuitem', { name: /停用账号|启用账号/ })).toHaveCount(0)
  await page.getByRole('menuitem', { name: '编辑姓名' }).click()
  const edit = page.getByRole('dialog', { name: '编辑姓名' })
  await expect(edit.getByLabel('账号')).toHaveAttribute('readonly', '')
  await edit.getByLabel('姓名').fill('  ')
  await edit.getByRole('button', { name: '保存', exact: true }).click()
  await expect(edit.getByText('请输入姓名')).toBeVisible()
  await edit.getByLabel('姓名').fill(renamed)
  await edit.getByRole('button', { name: '保存', exact: true }).click()
  await expect(edit).toHaveCount(0)
  await expect(row).toContainText(renamed)
  await row.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '查看工作' }).click()
  await expect(page).toHaveURL(/\/team\?.*view=work.*scope=current.*member=/)
  await expect(page.getByRole('heading', { name: '暂无符合条件的工作' })).toBeVisible()
  await page.getByRole('link', { name: '返回成员管理' }).click()
  await expect(page.getByRole('textbox', { name: '搜索成员' })).toHaveValue(username.toUpperCase())
  await row.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '重置密码' }).click()
  const reset = page.getByRole('dialog', { name: `重置 ${renamed} 的密码` })
  await reset.getByLabel('密码').fill('2222')
  await reset.getByRole('button', { name: '保存', exact: true }).click()
  await expect(reset).toHaveCount(0)
  await page.getByRole('button', { name: '添加成员', exact: true }).click()
  const duplicate = page.getByRole('dialog', { name: '添加成员' })
  await duplicate.getByLabel('姓名').fill(name)
  await duplicate.getByLabel('账号').fill(username)
  await duplicate.getByLabel('密码').fill('1111')
  await duplicate.getByRole('button', { name: '保存', exact: true }).click()
  await expect(duplicate.getByLabel('账号')).toHaveAttribute('aria-invalid', 'true')
  await expect(duplicate.getByText('账号名称已被使用')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(duplicate).toHaveCount(0)
  await page.getByRole('button', { name: 'Noria 外观', exact: true }).click()
  await page
    .getByRole('dialog', { name: 'Noria 外观' })
    .getByRole('button', { name: '深色', exact: true })
    .click()
  await page.keyboard.press('Escape')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await capture('members-dark')
  await page.setViewportSize({ width: 390, height: 844 })
  await capture('members-mobile-dark')
  await row.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '编辑姓名' }).click()
  await capture('member-name-mobile-dark')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Noria 外观', exact: true }).click()
  await page
    .getByRole('dialog', { name: 'Noria 外观' })
    .getByRole('button', { name: '浅色', exact: true })
    .click()
  await page.keyboard.press('Escape')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await capture('members-mobile-light')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await row.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '删除账号' }).click()
  const remove = page.getByRole('dialog', { name: '删除账号' })
  await expect(remove.getByRole('button', { name: '删除账号', exact: true })).toBeEnabled()
  await remove.getByRole('button', { name: '删除账号', exact: true }).click()
  await expect(row).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '没有匹配的成员' })).toBeVisible()
  await capture('members-no-match')
  await create()
  await expect(row).toContainText(name)
  await capture('recreated-member')
})

test('W15 member list loading, failure, empty and long text states', async ({
  page,
  state,
  login,
  capture,
  http,
}) => {
  await login()
  const endpoint = '**/api/v1/members'
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(endpoint, async (route) => {
    await gate
    await route.continue()
  })
  await page.goto(state.origin + '/members')
  await expect(page.getByText('正在读取成员…')).toBeVisible()
  await capture('members-loading')
  release()
  await expect(page.getByText('正在读取成员…')).toHaveCount(0)
  await page.unroute(endpoint)
  await page.route(endpoint, (route) => route.abort('failed'))
  await page.reload()
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeVisible()
  await capture('members-error')
  await page.unroute(endpoint)
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.getByRole('table', { name: '成员列表' })).toBeVisible()
  await page.route(endpoint, (route) => route.fulfill({ json: { items: [] } }))
  await page.reload()
  await expect(page.getByRole('button', { name: '添加第一位成员' })).toBeVisible()
  await capture('members-empty')
  await page.unroute(endpoint)
  const username = `visual_${Date.now()}_${'long'.repeat(14)}`
  const created = await http<{ id: string }>('/api/v1/members', 'POST', {
    name: '团队协作成员'.repeat(12),
    username,
    password: '1111',
  })
  expect(created.status).toBe(201)
  try {
    await page.goto(state.origin + '/members?q=' + username)
    await expect(page.getByRole('table', { name: '成员列表' })).toBeVisible()
    await capture('members-long-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await capture('members-long-mobile')
    const row = page.getByRole('row').filter({ has: page.getByText(username, { exact: true }) })
    await row.getByRole('button', { name: '更多操作' }).click()
    await expect(page.getByRole('menuitem', { name: '编辑姓名' })).toBeVisible()
    await capture('members-long-mobile-actions')
  } finally {
    expect((await http('/api/v1/members/' + created.data.id, 'DELETE')).status).toBe(200)
  }
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
  await expect(page.getByRole('tab', { name: '反馈记录' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('button', { name: new RegExp(description) })).toBeVisible()
  await capture('employee-feedback')
  await page.goto(state.origin + '/settings/account')
  await page.getByRole('button', { name: '退出登录', exact: true }).last().click()
  await login()
  await page.goto(state.origin + '/settings/support')
  await page.getByRole('tab', { name: '反馈记录', exact: true }).click()
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
