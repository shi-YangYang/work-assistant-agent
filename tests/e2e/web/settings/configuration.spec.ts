import type { CompanyService, ModelRouting } from '@paa/api-contracts'
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
  const settings = page.getByRole('dialog', { name: '设置 synthetic-model' })
  await settings.getByLabel('使用流式接口').uncheck()
  for (const effort of ['low', 'high']) {
    await settings.getByLabel('可选思考强度').fill(effort)
    await settings.getByLabel('可选思考强度').press('Enter')
  }
  await settings.getByLabel('初始思考强度').selectOption('high')
  await settings.getByRole('button', { name: '完成', exact: true }).click()
  await page.getByRole('button', { name: '保存服务', exact: true }).click()
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('')
  const response = await http<{ services: CompanyService[] }>('/api/v1/settings/model-services')
  expect(response.status).toBe(200)
  expect(JSON.stringify(response.data)).not.toContain('synthetic-not-a-real-key')
  expect(JSON.stringify(response.data)).toContain(name)
  await page.reload()
  await expect(page.getByLabel('服务名称')).toHaveValue(name)
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('')
  await capture('saved-model-service')
  const stored = response.data.services.find((service) => service.name === name)!
  expect(stored.models[0].streaming).toBe(false)
  expect(stored.models[0].reasoning).toMatchObject({ efforts: ['low', 'high'], initial: 'high' })
  const before = await http<ModelRouting>('/api/v1/settings/model-routing')
  try {
    await page.getByRole('tab', { name: '用途分配', exact: true }).click()
    await expect(page.getByLabel('使用流式接口')).toHaveCount(0)
    await page
      .getByRole('combobox', { name: /^使用的模型/ })
      .first()
      .selectOption(`${stored.id}/${stored.models[0].id}`)
    await page.getByRole('button', { name: '保存用途分配', exact: true }).click()
    await expect(page.getByText('用途分配已保存', { exact: true })).toBeVisible()
    await page.goto(state.origin + '/assistant?new=1')
    await page.getByRole('button', { name: '思考强度：high', exact: true }).click()
    await expect(page.getByRole('menuitemradio')).toHaveCount(2)
    await expect(page.getByRole('menuitemradio', { name: 'low', exact: true })).toBeVisible()
    await expect(page.getByRole('menuitemradio', { name: 'high', exact: true })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    await capture('administrator-reasoning-options-in-composer')
  } finally {
    const current = await http<ModelRouting>('/api/v1/settings/model-routing')
    expect(
      (
        await http('/api/v1/settings/model-routing', 'PUT', {
          assistant: before.data.assistant,
          report: before.data.report,
          asr: before.data.asr,
          expectedRevision: current.data.revision,
        })
      ).status,
    ).toBe(200)
  }
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
