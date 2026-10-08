import { readFileSync, mkdirSync } from 'node:fs'
import { test, expect } from '../fixtures/test'

test('F03 download the real revised spreadsheet and image', async ({
  page,
  state,
  login,
  capture,
}) => {
  test.skip(
    !process.env.REAL_BROWSER_JOURNEYS,
    'Requires this run’s declared real model journey; owned by the real-model suite',
  )
  const entries = readFileSync(process.env.REAL_BROWSER_JOURNEYS!, 'utf8')
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line))
  const turn = entries.find((entry) => entry.command.text?.startsWith('A的退款额刚收到更正'))
  if (!turn?.result?.ui?.url) throw new Error('F03 real model journey is required')
  if (new URL(turn.result.ui.url).origin !== state.origin)
    throw new Error('Real journey does not belong to the owned UI origin')
  await login('realEmployee')
  await page.goto(turn.result.ui.url)
  mkdirSync(process.env.REAL_BROWSER_DOWNLOADS || 'artifacts/spec054/20261008-full/ui/downloads', {
    recursive: true,
  })
  for (const filename of ['净销售额明细与合计.xlsx', '净销售额汇总柱状图.png']) {
    const pending = page.waitForEvent('download')
    await page
      .getByRole('button', { name: '下载' + filename, exact: true })
      .last()
      .click()
    const download = await pending
    expect(download.suggestedFilename()).toBe(filename)
    await download.saveAs(
      (process.env.REAL_BROWSER_DOWNLOADS || 'artifacts/spec054/20261008-full/ui/downloads') +
        '/' +
        filename,
    )
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
  test.skip(
    !process.env.REAL_BROWSER_WORK,
    'Requires this run’s declared real-model work and expected revision',
  )
  const work = JSON.parse(readFileSync(process.env.REAL_BROWSER_WORK!, 'utf8')) as {
    runId: string
    schema: string
    id: string
    deadline: string
    expectedText: string
  }
  if (work.runId !== state.runId || work.schema !== state.schema)
    throw new Error('Real work does not belong to this run')
  await login('realEmployee')
  await page.goto(state.origin + '/work/' + encodeURIComponent(work.id))
  await expect(page.getByText('截止日期：' + work.deadline, { exact: true })).toBeVisible()
  await expect(page.getByText(work.expectedText, { exact: true }).first()).toBeVisible()
  await capture('plan-work-revised')
})
