import { test, expect } from '../fixtures/test'

test('W04 W06 W07 @cross draft, persona, execution mode and attachment previews', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login('employee')
  await page.goto(state.origin + '/assistant')
  await page.getByRole('button', { name: /选择人设/ }).click()
  await page.getByRole('menuitemradio', { name: /^专业人设/ }).click()
  await expect(page.getByRole('button', { name: '选择人设：专业人设' })).toBeVisible()
  await page.getByRole('button', { name: /执行权限/ }).click()
  await page.getByRole('menuitemradio', { name: /^逐项确认/ }).click()
  const text = page.getByRole('textbox', { name: '工作消息' })
  await text.fill('请帮我阅读附件，但先不要保存工作。')
  await text.press('Shift+Enter')
  await expect(text).toHaveValue(/\n$/)
  await page
    .locator('input[type=file]')
    .nth(1)
    .setInputFiles({
      name: '需求.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('客户希望两周内上线内部网站，预算待确认。'),
    })
  await expect(page.getByRole('button', { name: '移除需求.txt', exact: true })).toBeVisible()
  await capture('attachment')
  await page
    .getByRole('navigation', { name: '工作空间' })
    .getByRole('link', { name: '我的工作', exact: true })
    .click()
  await page
    .getByRole('navigation', { name: '工作空间' })
    .getByRole('link', { name: '工作助手', exact: true })
    .click()
  await expect(text).toHaveValue(/请帮我阅读附件/)
  await expect(page.getByRole('button', { name: '移除需求.txt', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '移除需求.txt', exact: true }).click()
  await expect(page.getByRole('button', { name: '移除需求.txt', exact: true })).toHaveCount(0)
  await capture('restored-draft')
})
