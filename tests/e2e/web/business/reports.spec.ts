import { readFileSync } from 'node:fs'
import { test, expect } from '../fixtures/test'

test('W13 W14 edit submit and read employee report as manager', async ({
  page,
  state,
  login,
  capture,
  http,
}) => {
  const report = JSON.parse(readFileSync('artifacts/spec044/environment/report.json', 'utf8')) as {
    id: string
  }
  await login('employee')
  await page.goto(`${state.origin}/reports/${report.id}`)
  await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
  await page.getByLabel('完成的工作').fill('核对了测试需求，完成字段校验')
  await page.getByLabel('问题与阻碍').fill('暂无阻碍')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('草稿已保存')).toBeVisible()
  await capture('edited-report')
  await page.getByRole('button', { name: '提交报告', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认提交', exact: true }).click()
  await expect(page.getByText('已提交第 2 版', { exact: true })).toBeVisible()
  const stored = await http<{ publishedRevision: number; content: { completed: string } }>(
    `/api/v1/reports/${report.id}`,
  )
  expect(stored.data.publishedRevision).toBe(2)
  expect(stored.data.content.completed).toContain('完成字段校验')
  await capture('published-report')
  await page.goto(state.origin + '/settings/account')
  await page.getByRole('button', { name: '退出登录', exact: true }).last().click()
  await login()
  await page.goto(`${state.origin}/reports/${report.id}`)
  await expect(page.getByText('核对了测试需求，完成字段校验', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '编辑草稿', exact: true })).toHaveCount(0)
  await capture('manager-read-report')
})
