import { readFileSync } from 'node:fs'
import { test, expect } from '../fixtures/test'

test('work body and checklist → real worker weekly report → submit → team read → delete and rebuild', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login('employee')
  const records = JSON.parse(readFileSync(process.env.UI_LAYOUT_RECORDS!, 'utf8'))
  const seeded = await http<{ managementRevision: number }>(
    `/api/v1/reports/${records.employee.weekly}`,
  )
  expect(
    (
      await http(`/api/v1/reports/${records.employee.weekly}`, 'DELETE', {
        expectedRevision: seeded.data.managementRevision,
      })
    ).status,
  ).toBe(200)
  await page.goto(state.origin + '/work')
  await page.getByRole('button', { name: '新建工作', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新建工作' })
  await dialog.getByRole('textbox', { name: '工作事项' }).fill('项目测试需求')
  await dialog.getByRole('button', { name: '创建工作', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  const workId = new URL(page.url()).pathname.split('/').at(-1)!
  await page.getByRole('button', { name: '编辑内容' }).click()
  await page.getByRole('textbox', { name: '工作正文' }).fill('已整理项目测试需求')
  await page.getByRole('button', { name: '勾选清单', exact: true }).click()
  await page.getByLabel('正文材料').setInputFiles({
    name: '需求.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('合成工作材料'),
  })
  await page.getByRole('button', { name: '保存内容' }).click()
  await expect(page.getByRole('button', { name: '编辑内容' })).toBeVisible()
  await page.reload()
  const work = await http<{ bodyText: string; materialIds: string[] }>(
    `/api/v1/work-items/${workId}`,
  )
  expect(work.data.bodyText).toContain('已整理项目测试需求')
  expect(work.data.materialIds).toHaveLength(1)
  async function generate() {
    await page.goto(state.origin + '/reports')
    await page.getByRole('button', { name: '全部报告', exact: true }).click()
    const response = page.waitForResponse(
      (r) => r.url().endsWith('/api/v1/reports/generate') && r.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '生成周报', exact: true }).click()
    const generated = await response
    expect(generated.ok()).toBe(true)
    const { reportId } = await generated.json()
    await expect
      .poll(
        async () =>
          (await http<{ content: { completed?: string } }>(`/api/v1/reports/${reportId}`)).data
            .content.completed,
        { timeout: 30000 },
      )
      .toBe('已整理项目测试需求')
    await page.goto(state.origin + '/reports/' + reportId)
    return reportId as string
  }
  const reportId = await generate()
  await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
  await page.getByLabel('完成的工作').fill('已整理项目测试需求，并核对材料')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await page.getByRole('button', { name: '提交报告', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认提交', exact: true }).click()
  await page.reload()
  await expect(page.getByText('已整理项目测试需求，并核对材料', { exact: true })).toBeVisible()
  await capture('weekly-persisted')
  await page.goto(state.origin + '/settings/account')
  await page.getByRole('button', { name: '退出登录', exact: true }).last().click()
  await login('admin')
  await page.goto(state.origin + '/reports/' + reportId)
  await expect(page.getByText('已整理项目测试需求，并核对材料', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '管理报告' }).click()
  await page.getByRole('menuitem', { name: '删除报告' }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认删除', exact: true }).click()
  expect((await http('/api/v1/reports/' + reportId)).status).toBe(404)
  await page.goto(state.origin + '/settings/account')
  await page.getByRole('button', { name: '退出登录', exact: true }).last().click()
  await login('employee')
  const rebuilt = await generate()
  expect(rebuilt).not.toBe(reportId)
  await capture('weekly-rebuilt')
})
