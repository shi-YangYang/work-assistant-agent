import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

async function bounded<T>(
  operation: Promise<T>,
  milliseconds: number,
  message: string,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      operation,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(message)), milliseconds)
      }),
    ])
  } finally {
    clearTimeout(timer)
  }
}

async function closeWindow(app: ElectronApplication): Promise<void> {
  await Promise.all([
    app.waitForEvent('close', { timeout: 10_000 }),
    app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close()),
  ])
}

test('real local model restores transcript, seeks, and generates historical text across platforms', async () => {
  test.skip(
    process.env.PAA_REAL_ASR_SMOKE !== '1',
    'Run npm run test:asr first; CI requires this real-model scenario',
  )
  test.setTimeout(120_000)
  const fixture = JSON.parse(readFileSync('artifacts/spec003/real-asr.json', 'utf8')) as {
    dataRoot: string
    meetingId: string
    resumeId: string
    historyId: string
  }
  const events: { stage: string; state: string; elapsedMs: number; detail?: unknown }[] = []
  const started = Date.now()
  const record = (stage: string, state: string, detail?: unknown): void => {
    events.push({ stage, state, elapsedMs: Date.now() - started, detail })
    writeFileSync(
      'artifacts/spec003/transcription-smoke-stages.json',
      JSON.stringify({ platform: process.platform, events }, null, 2),
    )
  }
  const step = async <T>(name: string, action: () => Promise<T>): Promise<T> => {
    record(name, 'started')
    try {
      const result = await test.step(name, action)
      record(name, 'completed')
      return result
    } catch (error) {
      record(name, 'failed', String(error))
      throw error
    }
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
  let app = await step('launch desktop', launch)
  let cleanupFailure: unknown
  try {
    let page = await app.firstWindow()
    const historyIndex = await step('restore existing transcript and seek', async () => {
      await expect
        .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
        .toBe('ready')
      await page.getByRole('button', { name: '本地转写模型', exact: true }).click()
      await expect(page.getByText('模型已就绪', { exact: true })).toBeVisible({ timeout: 30_000 })
      await page.getByRole('button', { name: '会议记录', exact: true }).click()
      const meetings = await page.evaluate(() => window.paa.listMeetings())
      if (!meetings.ok) throw new Error(meetings.message)
      const completedIndex = meetings.meetings.findIndex(
        (meeting) => meeting.id === fixture.meetingId,
      )
      const index = meetings.meetings.findIndex((meeting) => meeting.id === fixture.historyId)
      expect(completedIndex).toBeGreaterThanOrEqual(0)
      expect(index).toBeGreaterThanOrEqual(0)
      await page.locator('.meeting-row').nth(completedIndex).click()
      await page.getByRole('tab', { name: '文字记录', exact: true }).click()
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
      return index
    })
    const saved = await step('generate historical transcript', async () => {
      await page.getByRole('button', { name: '返回会议列表', exact: true }).click()
      await page.locator('.meeting-row').nth(historyIndex).click()
      await page.getByRole('tab', { name: '文字记录', exact: true }).click()
      await expect(page.getByRole('button', { name: '生成转写', exact: true })).toBeEnabled()
      await page.getByRole('button', { name: '生成转写', exact: true }).click()
      await expect(page.getByLabel('会议文字')).toContainText('转写完成', { timeout: 30_000 })
      await expect(page.getByLabel('会议文字')).toContainText('中介协会分析')
      const result = await page.evaluate((id) => window.paa.listTranscript(id), fixture.historyId)
      await page.screenshot({ path: 'artifacts/spec003/real-transcript-desktop.png' })
      return result
    })
    await step('close completed desktop and restart', async () => {
      await closeWindow(app)
      app = await launch()
      page = await app.firstWindow()
      await expect
        .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
        .toBe('ready')
      expect(await page.evaluate((id) => window.paa.listTranscript(id), fixture.historyId)).toEqual(
        saved,
      )
      await page.locator('.meeting-row').nth(historyIndex).click()
      await page.getByRole('tab', { name: '文字记录', exact: true }).click()
      await expect(page.getByLabel('会议文字')).toContainText('转写完成')
    })
    await step('cancel close while real transcription is active', async () => {
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
        .poll(() =>
          app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getTitle()),
        )
        .toBe('转写关闭确认已取消')
      expect(
        await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible()),
      ).toBe(true)
    })
    await step('preserve progress and close', async () => {
      await app.evaluate(({ dialog }) => {
        dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
      })
      await closeWindow(app)
    })
    await step('restart with paused transcription', async () => {
      app = await launch()
      page = await app.firstWindow()
      await expect
        .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
        .toBe('ready')
      const paused = await page.evaluate(
        (id) => window.paa.getTranscriptionStatus(id),
        fixture.resumeId,
      )
      record('resume status after restart', 'observed', paused)
      expect(paused.ok && paused.value.state).toBe('paused')
    })
    await step('continue remaining audio to completion', async () => {
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
            record('continuing transcription', 'observed', result)
            return result.ok && result.value.state
          },
          { timeout: 60_000 },
        )
        .toBe('completed')
    })
  } finally {
    const child = app.process()
    if (child.exitCode === null && child.signalCode === null) {
      record('cleanup', 'started')
      try {
        // A failed assertion can leave real work active. Answer the test app's exit
        // prompt before closing; app.close() would disconnect its main debugger first.
        await bounded(
          app.evaluate(({ dialog }) => {
            dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false })
          }),
          2_000,
          'Unable to answer the test desktop exit prompt',
        )
        await closeWindow(app)
        record('cleanup', 'completed')
      } catch (error) {
        record('cleanup', 'failed', String(error))
        if (child.pid && child.exitCode === null && child.signalCode === null) {
          try {
            if (process.platform === 'win32') {
              execFileSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
                timeout: 3_000,
                stdio: 'ignore',
              })
            } else child.kill('SIGKILL')
          } catch (cleanupError) {
            record('cleanup process termination', 'failed', String(cleanupError))
          }
        }
        cleanupFailure = error
      }
    }
  }
  // A body error propagates past this point unchanged. Only a successful body
  // reaches here, so failed cleanup still fails the test without masking it.
  if (cleanupFailure) throw cleanupFailure
})
