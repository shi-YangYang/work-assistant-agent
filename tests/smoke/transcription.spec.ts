import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

test('real local model restores transcript, seeks, and generates historical text across platforms', async () => {
  test.skip(
    process.env.PAA_REAL_ASR_SMOKE !== '1',
    'Run npm run test:asr first; CI requires this real-model scenario',
  )
  test.setTimeout(90_000)
  const fixture = JSON.parse(readFileSync('artifacts/spec003/real-asr.json', 'utf8')) as {
    dataRoot: string
    meetingId: string
    resumeId: string
    historyId: string
  }
  const launch = async (): Promise<ElectronApplication> => {
    const env = Object.fromEntries(
      Object.entries({ ...process.env, PAA_TEST_DATA_DIR: fixture.dataRoot }).filter(
        (entry): entry is [string, string] => typeof entry[1] === 'string',
      ),
    )
    delete env.ELECTRON_RUN_AS_NODE
    delete env.ELECTRON_RENDERER_URL
    return electron.launch({ args: ['--use-fake-device-for-media-stream', resolve('.')], env })
  }
  let app = await launch()
  try {
    let page = await app.firstWindow()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('ready')
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await expect(page.getByText('模型已就绪', { exact: true })).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: '会议记录', exact: true }).click()
    const meetings = await page.evaluate(() => window.paa.listMeetings())
    if (!meetings.ok) throw new Error(meetings.message)
    const completedIndex = meetings.meetings.findIndex(
      (meeting) => meeting.id === fixture.meetingId,
    )
    const historyIndex = meetings.meetings.findIndex((meeting) => meeting.id === fixture.historyId)
    expect(completedIndex).toBeGreaterThanOrEqual(0)
    expect(historyIndex).toBeGreaterThanOrEqual(0)
    await page.locator('.meeting-row').nth(completedIndex).click()
    await expect(page.getByLabel('会议文字')).toContainText('中介协会分析')
    await page.locator('.transcript-line').first().click()
    await expect
      .poll(() =>
        page.locator('audio').evaluate((element) => (element as HTMLAudioElement).currentTime),
      )
      .toBeGreaterThan(0)
    for (const cursor of [-2, 1.5, 1_000_000_001]) {
      expect(
        await page.evaluate(
          async ({ id, cursor }) => {
            try {
              await window.paa.listTranscript(id, cursor)
              return false
            } catch {
              return true
            }
          },
          { id: fixture.meetingId, cursor },
        ),
      ).toBe(true)
    }
    await page.getByRole('button', { name: '返回会议列表', exact: true }).click()
    await page.locator('.meeting-row').nth(historyIndex).click()
    await expect(page.getByRole('button', { name: '生成转写', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: '生成转写', exact: true }).click()
    await expect(page.getByLabel('会议文字')).toContainText('转写完成', { timeout: 30_000 })
    await expect(page.getByLabel('会议文字')).toContainText('中介协会分析')
    const saved = await page.evaluate((id) => window.paa.listTranscript(id), fixture.historyId)
    await page.screenshot({ path: 'artifacts/spec003/real-transcript-desktop.png' })
    await app.close()
    app = await launch()
    page = await app.firstWindow()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('ready')
    expect(await page.evaluate((id) => window.paa.listTranscript(id), fixture.historyId)).toEqual(
      saved,
    )
    await page.locator('.meeting-row').nth(historyIndex).click()
    await expect(page.getByLabel('会议文字')).toContainText('转写完成')
    // A longer public speech fixture gives the close guard actual work to pause.
    await expect
      .poll(async () => {
        const result = await page.evaluate(() => window.paa.getTranscriptionModel())
        return result.ok && result.value.state
      })
      .toBe('ready')
    await page.evaluate((id) => window.paa.startTranscription(id), fixture.resumeId)
    await app.evaluate(({ dialog, BrowserWindow }) => {
      dialog.showMessageBox = async () => {
        BrowserWindow.getAllWindows()[0].setTitle('转写关闭确认已取消')
        return { response: 0, checkboxChecked: false }
      }
    })
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    await expect
      .poll(() => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getTitle()))
      .toBe('转写关闭确认已取消')
    expect(
      await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()),
    ).toBe(true)
    await app.evaluate(({ dialog }) => {
      dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
    })
    const closed = app.waitForEvent('close')
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close())
    await closed
    app = await launch()
    page = await app.firstWindow()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('ready')
    const paused = await page.evaluate(
      (id) => window.paa.getTranscriptionStatus(id),
      fixture.resumeId,
    )
    expect(paused.ok && paused.value.state).toBe('paused')
    await expect
      .poll(async () => {
        const result = await page.evaluate(() => window.paa.getTranscriptionModel())
        return result.ok && result.value.state
      })
      .toBe('ready')
    await page.evaluate((id) => window.paa.startTranscription(id), fixture.resumeId)
    await expect
      .poll(
        async () => {
          const result = await page.evaluate(
            (id) => window.paa.getTranscriptionStatus(id),
            fixture.resumeId,
          )
          return result.ok && result.value.state
        },
        { timeout: 30_000 },
      )
      .toBe('completed')
  } finally {
    await app.close().catch(() => {})
  }
})
