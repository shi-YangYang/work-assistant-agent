import { test, expect } from '../fixtures/test'

test('W17 real voiceprint upload, extract and removal', async ({ page, state, login, capture }) => {
  test.setTimeout(240_000)
  await login()
  await page.goto(state.origin + '/settings/voiceprints')
  const row = page.locator('article').filter({ hasText: '合成测试 employee' })
  await row.getByRole('button', { name: '上传录音', exact: true }).click()
  const form = page.getByRole('dialog')
  await form
    .getByLabel('登记录音', { exact: true })
    .setInputFiles('artifacts/spec044/agent/materials/enrollment.wav')
  await expect(form.getByRole('button', { name: '上传并提取声纹' })).toBeDisabled()
  await form.getByRole('checkbox').check()
  await form.getByRole('button', { name: '上传并提取声纹' }).click()
  await expect(form).toHaveCount(0)
  await expect(row).toContainText('已就绪', { timeout: 180_000 })
  await expect(row).toContainText(/有效声音 \d+/)
  await capture('real-voiceprint-ready')
  page.on('dialog', async (dialog) => {
    await dialog.accept()
  })
  await row.getByRole('button', { name: /删除.*声纹/ }).click()
  await expect(row).toContainText('未登记')
  await expect(row.getByRole('button', { name: /删除.*声纹/ })).toHaveCount(0)
})
