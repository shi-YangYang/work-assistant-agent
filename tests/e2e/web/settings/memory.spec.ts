import type { AssistantMemory } from '@paa/api-contracts'
import { test, expect } from '../fixtures/test'

test('W21 @cross memory edit, switch stability, conflict recovery and explicit clear', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login('employee')
  await page.goto(state.origin + '/settings/memory')
  const toggle = page.getByRole('switch', { name: '启用跨会话记忆' })
  const edit = page.getByRole('button', { name: '编辑', exact: true })
  await expect(edit).toBeVisible()
  await edit.click()
  const editor = page.getByRole('textbox', { name: '记忆 Markdown' })
  const draft = '# 我的偏好\n\n- 简明中文\n- 先给结论，再说明依据'
  await editor.fill(draft)
  await page.getByRole('button', { name: '预览', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的偏好' })).toBeVisible()
  await page.getByRole('button', { name: '继续编辑', exact: true }).click()
  await expect(editor).toHaveValue(draft)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(edit).toBeVisible()
  const editNode = await edit.elementHandle()
  const toggleNode = await toggle.elementHandle()
  const previous = await toggle.getAttribute('aria-checked')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', previous === 'true' ? 'false' : 'true')
  expect(await editNode!.evaluate((node) => node.isConnected)).toBe(true)
  expect(await toggleNode!.evaluate((node) => node.isConnected)).toBe(true)
  await expect(page.getByRole('heading', { name: '我的偏好' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: '我的偏好' })).toBeVisible()
  await capture('memory-persisted-switch')
  await edit.click()
  await editor.fill(draft + '\n- 本地未保存补充')
  const current = await http<AssistantMemory>('/api/v1/assistant/memory')
  const remote = await http<AssistantMemory>('/api/v1/assistant/memory/document', 'PUT', {
    markdown: '# 另一标签页已保存',
    expectedRevision: current.data.revision,
  })
  expect(remote.status).toBe(200)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('已保留你的草稿。读取最新文档，合并后再保存。')).toBeVisible()
  await expect(editor).toHaveValue(/本地未保存补充/)
  await page.getByRole('button', { name: '读取最新版本' }).click()
  await expect(page.getByRole('heading', { name: '另一标签页已保存' })).toBeVisible()
  await capture('memory-concurrent-conflict')
  await page.getByRole('button', { name: '已核对，保留草稿继续编辑' }).click()
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(edit).toBeVisible()
  await edit.click()
  await editor.fill('取消的草稿')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByText('取消的草稿')).toHaveCount(0)
  const conversation = await http<{ id: string; revision: number }>(
    '/api/v1/conversations',
    'POST',
    {
      personaId: 'professional',
    },
  )
  expect(conversation.status).toBe(201)
  expect(
    (
      await http(`/api/v1/conversations/${conversation.data.id}`, 'DELETE', {
        expectedRevision: conversation.data.revision,
      })
    ).status,
  ).toBe(200)
  expect((await http<AssistantMemory>('/api/v1/assistant/memory')).data.markdown).toContain(
    '本地未保存补充',
  )
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByRole('button', { name: '清空记忆' }).click()
  await expect(page.getByRole('heading', { name: '我的偏好' })).toBeVisible()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: '清空记忆' }).click()
  await expect(page.getByText(/还没有记忆/)).toBeVisible()
  await capture('memory-explicit-clear')
})
