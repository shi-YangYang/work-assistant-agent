import type { Work, WorkPageResult, WorkUpdate } from '@paa/api-contracts'
import { test, expect } from '../fixtures/test'

const image = {
  name: '客户截图.png',
  mimeType: 'image/png',
  buffer: Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9i8AAAAASUVORK5CYII=',
    'base64',
  ),
}
const document = {
  name: '客户需求.txt',
  mimeType: 'text/plain',
  buffer: Buffer.from('官网需要支持移动端与在线询价。'),
}

test('W01-W04 W14 @cross title body materials updates and latest chat reference', async ({
  page,
  state,
  login,
  capture,
  http,
}, info) => {
  const title = `工作内容验收-${info.project.name}-${Date.now()}`
  await login('employee')
  await page.goto(state.origin + '/work')
  await page.getByRole('button', { name: '新建工作', exact: true }).click()
  const create = page.getByRole('dialog', { name: '新建工作' })
  await create.getByRole('button', { name: '创建工作', exact: true }).click()
  await expect(create).toBeVisible()
  await create.getByRole('textbox', { name: '工作事项' }).fill(title)
  await expect(create.getByLabel('当前进展')).toHaveCount(0)
  await create.getByRole('button', { name: '创建工作', exact: true }).click()
  await expect(create).toHaveCount(0)
  await expect(page).toHaveURL(/\/work\/[a-z0-9-]+$/)
  const id = new URL(page.url()).pathname.split('/').at(-1)!
  await capture('title-only')
  await page.getByRole('button', { name: '编辑正文' }).click()
  await page.getByRole('textbox', { name: '工作正文' }).fill('先整理客户需求，再完成首页设计。')
  await page.getByRole('button', { name: '勾选清单', exact: true }).click()
  await page.getByLabel('正文材料').setInputFiles([image, document])
  await expect(page.getByRole('button', { name: '保存正文' })).toBeEnabled()
  await expect(page.getByText('保存后，材料随这项工作可见。')).toBeVisible()
  await page.getByRole('button', { name: '保存正文' }).click()
  await expect(page.getByRole('button', { name: '编辑正文' })).toBeVisible()
  const content = await http<Work>(`/api/v1/work-items/${id}`)
  expect(content.data.bodyText).toContain('先整理客户需求')
  expect(content.data.materialIds).toHaveLength(2)
  expect(content.data.summary).toBe('')
  const originalBody = content.data.body
  await page.reload()
  await expect(page.getByRole('button', { name: '预览 客户截图.png' })).toBeVisible()
  await capture('body-and-materials')
  await page.getByRole('button', { name: '预览 客户截图.png' }).click()
  await expect(page.getByRole('dialog', { name: '客户截图.png' })).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '记录新进展' }).click()
  await page.getByLabel('记录新进展', { exact: true }).fill('客户已确认初稿，移动端待评审。')
  await page.getByRole('button', { name: '保存进展' }).click()
  await expect(page.getByText('客户已确认初稿，移动端待评审。', { exact: true })).toBeVisible()
  const updated = await http<Work>(`/api/v1/work-items/${id}`)
  expect(updated.data.body).toEqual(originalBody)
  expect(updated.data.status).toBe('in_progress')
  await page.getByRole('button', { name: '管理进展' }).click()
  await page.getByRole('menuitem', { name: '更正进展' }).click()
  const edit = page.getByRole('dialog', { name: '更正进展' })
  await edit.getByLabel('更正进展', { exact: true }).fill('客户已确认初稿，移动端周四评审。')
  await edit.getByRole('button', { name: '保存更正' }).click()
  await expect(edit).toHaveCount(0)
  const updates = await http<WorkPageResult<WorkUpdate>>(`/api/v1/work-items/${id}/updates`)
  expect(updates.data.items).toHaveLength(1)
  expect(updates.data.items[0]).toMatchObject({
    revision: 2,
    text: '客户已确认初稿，移动端周四评审。',
    origin: 'manual',
  })
  await page.getByRole('button', { name: '编辑工作', exact: true }).click()
  const properties = page.getByRole('dialog', { name: '编辑工作属性' })
  await properties.getByLabel('截止日期（选填）').fill('2026-10-09')
  await properties.getByRole('button', { name: '保存属性' }).click()
  await expect(properties).toHaveCount(0)
  expect((await http<Work>(`/api/v1/work-items/${id}`)).data.body).toEqual(originalBody)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '记录新进展' }).click()
  await page.getByLabel('进展材料').setInputFiles(document)
  await expect(page.getByText('保存后，材料随这项工作可见。')).toBeVisible()
  await page.getByRole('button', { name: '保存进展' }).click()
  await expect(page.getByRole('button', { name: '记录新进展' })).toBeVisible()
  await capture('mobile-progress')
  const fileUpdate = (await http<WorkPageResult<WorkUpdate>>(`/api/v1/work-items/${id}/updates`))
    .data.items[0]
  expect(fileUpdate.text).toBe('')
  expect(fileUpdate.materialIds).toHaveLength(1)
  await page.getByRole('button', { name: '管理进展' }).first().click()
  await page.getByRole('menuitem', { name: '删除进展' }).click()
  const deletion = page.getByRole('dialog', { name: '删除进展' })
  await deletion.getByRole('button', { name: '删除进展', exact: true }).click()
  await expect(deletion).toHaveCount(0)
  const remaining = await http<WorkPageResult<WorkUpdate>>(`/api/v1/work-items/${id}/updates`)
  expect(remaining.data.items).toHaveLength(1)
  expect(remaining.data.items[0].id).toBe(updates.data.items[0].id)
  await page.getByRole('button', { name: '让助手协助' }).click()
  await expect(page.getByRole('textbox', { name: '工作消息' })).toBeVisible()
  await expect(page.getByText(title, { exact: true }).last()).toBeVisible()
  await capture('work-reference')
})

test('W08 concurrent rich content save keeps draft and exposes explicit recovery', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login('employee')
  const created = await http<Work>('/api/v1/work-items', 'POST', { title: '并发正文验证' })
  const url = state.origin + '/work/' + created.data.id
  await page.goto(url)
  await page.getByRole('button', { name: '编辑正文' }).click()
  await page.getByRole('textbox', { name: '工作正文' }).fill('我的待保存版本')
  const competing = await http(`/api/v1/work-items/${created.data.id}`, 'PATCH', {
    expectedRevision: created.data.revision,
    body: {
      schemaVersion: 1,
      content: [{ type: 'paragraph', content: [{ type: 'text', text: '另一位编辑刚保存的版本' }] }],
    },
  })
  expect(competing.status).toBe(200)
  await page.getByRole('button', { name: '保存正文' }).click()
  await expect(page.getByRole('button', { name: '读取最新版本' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '工作正文' }).first()).toContainText(
    '我的待保存版本',
  )
  await page.getByRole('button', { name: '读取最新版本' }).click()
  await expect(page.getByText('另一位编辑刚保存的版本', { exact: true })).toBeVisible()
  await capture('conflict-retains-draft')
  await page.getByRole('button', { name: '使用最新内容' }).click()
  await expect(page.getByRole('textbox', { name: '工作正文' })).toContainText(
    '另一位编辑刚保存的版本',
  )
  await page.getByRole('button', { name: '取消', exact: true }).click()
  expect((await http<Work>(`/api/v1/work-items/${created.data.id}`)).data.bodyText).toBe(
    '另一位编辑刚保存的版本',
  )
})
