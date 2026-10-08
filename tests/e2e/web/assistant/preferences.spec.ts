import { test, expect } from '../fixtures/test'

test('W22 @cross execution permission applies across conversations and survives reload', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login('employee')
  const trigger = page.getByRole('button', { name: /^执行权限：/ })
  for (const name of ['逐项确认', '自动审核', '自主执行']) {
    await trigger.click()
    await expect(page.getByRole('menuitemradio')).toHaveCount(3)
    await page.getByRole('menuitemradio', { name: new RegExp('^' + name) }).click()
    if (
      name === '自主执行' &&
      (await page.getByRole('dialog', { name: '开启自主执行' }).isVisible())
    )
      await page
        .getByRole('dialog', { name: '开启自主执行' })
        .getByRole('button', { name: '开启自主执行', exact: true })
        .click()
    await expect(trigger).toHaveAccessibleName('执行权限：' + name)
    await page.getByRole('button', { name: '新会话', exact: true }).click()
    await expect(trigger).toHaveAccessibleName('执行权限：' + name)
    await page.reload()
    await expect(trigger).toHaveAccessibleName('执行权限：' + name)
  }
  await capture('account-global-permission')
  await trigger.click()
  await page.getByRole('menuitemradio', { name: /^自动审核/ }).click()
  await expect(trigger).toHaveAccessibleName('执行权限：自动审核')
  await page.goto(state.origin + '/assistant')
  await expect(page.getByRole('link', { name: '聊天搭子', exact: true })).toBeVisible()
  const cloud = page.getByText('云搭子', { exact: true })
  await expect(cloud).toBeVisible()
})

test('W23 @cross controlled reasoning options save by keyboard and appear in the submitted snapshot', async ({
  page,
  login,
  capture,
}) => {
  let settings = {
    options: [{ effort: 'low' }, { effort: 'high' }, { effort: 'max' }],
    selected: { effort: 'high' },
    preferenceRevision: 1,
    configVersion: 'synthetic-ui-config',
  }
  let saved: unknown
  let sent: Record<string, unknown> | undefined
  await page.route('**/api/v1/assistant/reasoning-settings', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      saved = body
      settings = {
        ...settings,
        selected: { effort: body.effort },
        preferenceRevision: settings.preferenceRevision + 1,
      }
    }
    await route.fulfill({ json: settings })
  })
  await page.route('**/api/v1/messages', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    sent = route.request().postDataJSON()
    await route.fulfill({ status: 503, json: { detail: '受控发送失败：保留草稿' } })
  })
  await login('employee')
  const trigger = page.getByRole('button', { name: '思考强度：high' })
  await trigger.focus()
  await page.keyboard.press('ArrowDown')
  await expect(page.getByRole('menuitemradio')).toHaveCount(3)
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '思考强度：max' })).toBeFocused()
  expect(saved).toEqual({
    effort: 'max',
    preferenceRevision: 1,
    configVersion: 'synthetic-ui-config',
  })
  const editor = page.getByRole('textbox', { name: '工作消息' })
  await editor.fill('受控思考强度测试，不调用模型')
  await editor.press('Enter')
  await expect(page.getByRole('alert')).toBeVisible()
  expect(sent).toMatchObject({
    reasoning: { effort: 'max', preferenceRevision: 2, configVersion: 'synthetic-ui-config' },
  })
  await expect(editor).toHaveValue('受控思考强度测试，不调用模型')
  await capture('reasoning-controlled-submit')
})
