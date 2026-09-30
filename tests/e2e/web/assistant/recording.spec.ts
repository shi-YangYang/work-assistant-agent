import { chromium } from '@playwright/test'
import { resolve } from 'node:path'
import { test, expect, login as signIn } from '../fixtures/test'

test('W05 fixed microphone input produces playable recording with duration', async ({ state }) => {
  const browser = await chromium.launch({
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${resolve('artifacts/spec044/agent/materials/audio.wav')}`,
    ],
  })
  try {
    const context = await browser.newContext({ permissions: ['microphone'] })
    const page = await context.newPage()
    await signIn(page, state, 'employee')
    await page.getByRole('button', { name: '新会话', exact: true }).click()
    await page.getByRole('button', { name: '录制语音', exact: true }).click()
    await expect(page.getByRole('button', { name: /停止录音 · [3-9] 秒/ })).toBeVisible({
      timeout: 10_000,
    })
    await page.getByRole('button', { name: /停止录音/ }).click()
    const audio = page.getByLabel(/^试听/)
    await expect(audio).toBeVisible()
    await expect
      .poll(() => audio.evaluate((node: HTMLAudioElement) => node.duration))
      .toBeGreaterThan(2)
    await audio.evaluate((node: HTMLAudioElement) => node.play())
    await expect
      .poll(() => audio.evaluate((node: HTMLAudioElement) => node.currentTime))
      .toBeGreaterThan(0.1)
    await audio.evaluate((node: HTMLAudioElement) => node.pause())
    await page.screenshot({ path: test.info().outputPath('recording-ready.png') })
  } finally {
    await browser.close()
  }
})
