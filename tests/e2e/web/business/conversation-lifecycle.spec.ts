import { readFileSync } from 'node:fs'
import { test, expect } from '../fixtures/test'

test('two attachment batches → real worker question → refresh → approval → one persisted work', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login('employee')
  await page.goto(state.origin + '/assistant?new=1')
  await page.getByRole('button', { name: /执行权限/ }).click()
  await page.getByRole('menuitemradio', { name: /^逐项确认/ }).click()
  const input = page.locator('input[type=file]').nth(1)
  await input.setInputFiles({
    name: '第一批.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('第一批合成需求'),
  })
  await expect(page.getByRole('button', { name: '移除第一批.txt', exact: true })).toBeVisible()
  await input.setInputFiles({
    name: '第二批.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('第二批合成范围'),
  })
  await expect(page.getByRole('button', { name: '移除第二批.txt', exact: true })).toBeVisible()
  await page
    .getByRole('textbox', { name: '工作消息' })
    .fill('PROJECT_CONVERSATION_FLOW 请根据两批材料新建工作，先问方向，再逐项确认后写入。')
  const response = page.waitForResponse(
    (r) => r.url().endsWith('/api/v1/messages') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const sent = await (await response).json()
  const message = await http<{ attachments: unknown[] }>(`/api/v1/messages/${sent.messageId}`)
  expect(message.data.attachments).toHaveLength(2)
  await expect(page.getByRole('region', { name: '回答助手问题' })).toBeVisible({ timeout: 30000 })
  await capture('question-desktop-light')
  await page.reload()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: /^Noria(?:，|$)/ }).click()
  await page
    .getByRole('dialog', { name: 'Noria', exact: true })
    .getByRole('button', { name: '深色', exact: true })
    .click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('region', { name: '回答助手问题' })).toBeVisible()
  await expect(page.getByRole('radio', { name: '测试整理', exact: true })).toBeVisible()
  await capture('question-mobile-dark')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('link', { name: '下载第一批.txt', exact: true }).click()
  const download = await downloadPromise
  expect(readFileSync((await download.path())!, 'utf8')).toBe('第一批合成需求')
  const panel = page.getByRole('region', { name: '回答助手问题' })
  await expect(panel).toBeVisible()
  await panel.getByRole('radio', { name: '测试整理', exact: true }).check()
  await panel.getByRole('button', { name: '提交回答' }).click()
  await expect(page.getByRole('button', { name: '确认创建工作', exact: true })).toBeVisible({
    timeout: 30000,
  })
  await capture('approval-mobile-dark')
  const before = await http<{ items: { id: string; title: string }[] }>(
    '/api/v1/work-items?q=' + encodeURIComponent('分批材料确认工作'),
  )
  expect(before.data.items).toHaveLength(0)
  await page.reload()
  await page.getByRole('button', { name: '确认创建工作', exact: true }).click()
  await expect
    .poll(
      async () =>
        (
          await http<{ items: { id: string; title: string }[] }>(
            '/api/v1/work-items?q=' + encodeURIComponent('分批材料确认工作'),
          )
        ).data.items.length,
      { timeout: 30000 },
    )
    .toBe(1)
  const saved = await http<{ items: { id: string }[] }>(
    '/api/v1/work-items?q=' + encodeURIComponent('分批材料确认工作'),
  )
  await page.goto(state.origin + '/work/' + saved.data.items[0].id)
  await expect(page.getByText('依据两批合成材料建立工作', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('依据两批合成材料建立工作', { exact: true })).toBeVisible()
  await capture('conversation-approved-work')
})
