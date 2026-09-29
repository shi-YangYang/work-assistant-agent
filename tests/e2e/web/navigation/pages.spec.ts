import { test, expect } from '../fixtures/test'

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
    await capture('desktop-light')
    await page.getByRole('button', { name: '切换深色' }).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await capture('mobile-dark')
    await page.setViewportSize({ width: 360, height: 780 })
    await page.getByRole('button', { name: '切换浅色' }).click()
    await capture('mobile-light')
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
  await page.getByRole('button', { name: '全部报告', exact: true }).click()
  await page.getByRole('button', { name: '周报', exact: true }).click()
  await expect(page.getByRole('button', { name: '生成周报', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '汇报安排', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await capture('employee-reports-weekly')
})
