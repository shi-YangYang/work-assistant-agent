import { test, expect } from '../fixtures/test'

test('D06 offline send preserves draft and shows one error without automatic replay', async ({
  page,
  context,
  login,
  capture,
}) => {
  await login('employee')
  await page.getByRole('button', { name: '新会话', exact: true }).click()
  const editor = page.getByRole('textbox', { name: '工作消息' })
  await expect(editor).toHaveValue('')
  const attempts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/messages')
      attempts.push(request.url())
  })
  await context.setOffline(true)
  await editor.fill('断网测试草稿，不应自动发送')
  await editor.press('Enter')
  await expect(page.getByRole('alert')).toHaveCount(1)
  await expect(editor).toHaveValue('断网测试草稿，不应自动发送')
  const firstAttempts = attempts.length
  // Observe the former polling interval; no retry click is made.
  await page.waitForTimeout(6500)
  expect(attempts.length).toBe(firstAttempts)
  await capture('one-offline-error')
  await context.setOffline(false)
  await page.waitForTimeout(1500)
  expect(attempts.length).toBe(firstAttempts)
  await expect(editor).toHaveValue('断网测试草稿，不应自动发送')
  await capture('restored-network-keeps-draft')
})
