import { test, expect } from '../fixtures/test'

test('W01 @cross login book validation and valid authentication', async ({
  page,
  state,
  login,
  capture,
}) => {
  await page.goto(state.origin)
  await expect(page.getByRole('button', { name: /直接登录/ })).toBeVisible()
  await capture('cover')
  await page.getByRole('button', { name: /直接登录/ }).click()
  await expect(page.getByText('请输入账号', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText('请输入账号', { exact: true })).toBeVisible()
  await expect(page.getByText('请输入密码', { exact: true })).toBeVisible()
  await capture('field-errors')
  await page.getByLabel('账号', { exact: true }).fill('spec044-missing-user')
  await page.getByLabel('密码', { exact: true }).fill('wrong-password')
  await page.getByRole('button', { name: '显示密码' }).click()
  await expect(page.getByLabel('密码', { exact: true })).toHaveAttribute('type', 'text')
  await page.getByRole('button', { name: '隐藏密码' }).click()
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText('账号或密码不正确，请重新输入。', { exact: true })).toBeVisible()
  await capture('incorrect-password')
  await login('employee')
  await expect(page.getByRole('textbox', { name: '工作消息' })).toBeVisible()
})

test('W02 @cross account switch isolates unsent draft and personal work', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login('admin')
  await page.goto(state.origin + '/assistant')
  await page.getByRole('textbox', { name: '工作消息' }).fill('管理员的私有未发送草稿')
  await page.goto(state.origin + '/settings/account')
  await page.getByRole('button', { name: '退出登录', exact: true }).last().click()
  await login('employee')
  await expect(page.getByRole('textbox', { name: '工作消息' })).toHaveValue('')
  await page.goto(state.origin + '/work')
  await expect(page.getByRole('link', { name: /合成验收工作 employee/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /合成验收工作 admin/ })).toHaveCount(0)
  await capture('switched-identity')
})
