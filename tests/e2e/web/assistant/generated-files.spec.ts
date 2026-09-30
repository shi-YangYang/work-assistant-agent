import { readFileSync, mkdirSync } from 'node:fs'
import { test, expect } from '../fixtures/test'

test('F03 download the real revised spreadsheet and image', async ({ page, login, capture }) => {
  const entries = readFileSync('artifacts/spec044/agent/browser/journeys.jsonl', 'utf8')
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line))
  const turn = entries.find((entry) => entry.command.text?.startsWith('A的退款额刚收到更正'))
  if (!turn?.result?.ui?.url) throw new Error('F03 real model journey is required')
  await login('realEmployee')
  await page.goto(turn.result.ui.url)
  mkdirSync('artifacts/spec044/agent/browser/downloads', { recursive: true })
  for (const filename of ['净销售额明细与合计.xlsx', '净销售额汇总柱状图.png']) {
    const pending = page.waitForEvent('download')
    await page
      .getByRole('button', { name: '下载' + filename, exact: true })
      .last()
      .click()
    const download = await pending
    expect(download.suggestedFilename()).toBe(filename)
    await download.saveAs('artifacts/spec044/agent/browser/downloads/' + filename)
    expect(await download.failure()).toBeNull()
  }
  await capture('revised-files')
})

test('F01 verify revised work in the actual detail page', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login('realEmployee')
  await page.goto(state.origin + '/work')
  await page.getByRole('link', { name: /补齐缺失材料/ }).click()
  await expect(page.getByText('截止日期：2026-10-05', { exact: true })).toBeVisible()
  await expect(page.getByText(/目标日期：2026-10-05 完成/).first()).toBeVisible()
  await capture('plan-work-revised')
})
