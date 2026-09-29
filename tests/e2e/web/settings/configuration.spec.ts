import { test, expect } from '../fixtures/test'

test('W16 manually configured model survives reload without exposing credential', async ({
  page,
  state,
  login,
  capture,
  http,
}) => {
  await login()
  await page.goto(state.origin + '/settings/models')
  await page.getByRole('button', { name: '添加服务', exact: true }).first().click()
  const name = `隔离配置-${Date.now()}`
  await page.getByLabel('服务名称').fill(name)
  await page.getByLabel('Base URL').fill('https://example.com/v1')
  await page.getByLabel('API 密钥', { exact: true }).fill('synthetic-not-a-real-key')
  await page.getByRole('button', { name: '手动添加', exact: true }).click()
  const modal = page.getByRole('dialog', { name: '手动添加模型' })
  await modal.getByLabel('模型 ID').fill('synthetic-model')
  await modal.getByRole('button', { name: '添加模型', exact: true }).click()
  await page
    .getByRole('dialog', { name: '设置 synthetic-model' })
    .getByRole('combobox', { name: '接口协议' })
    .selectOption('chat')
  await page
    .getByRole('dialog', { name: '设置 synthetic-model' })
    .getByRole('button', { name: '完成', exact: true })
    .click()
  await page.getByRole('button', { name: '保存服务', exact: true }).click()
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('')
  const response = await http('/api/v1/settings/model-services')
  expect(response.status).toBe(200)
  expect(JSON.stringify(response.data)).not.toContain('synthetic-not-a-real-key')
  expect(JSON.stringify(response.data)).toContain(name)
  await page.reload()
  await expect(page.getByLabel('服务名称')).toHaveValue(name)
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('')
  await capture('saved-model-service')
})

test('W01 DingTalk empty configuration shows field errors and remains disabled', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login()
  await page.goto(state.origin + '/settings/login')
  await page.getByRole('button', { name: '保存配置', exact: true }).click()
  await expect(page.getByLabel('企业 CorpId')).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByLabel('Client ID / AppKey')).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByLabel('Client Secret / AppSecret')).toHaveAttribute('aria-invalid', 'true')
  await capture('dingtalk-field-errors')
})
