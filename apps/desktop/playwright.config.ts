import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

export default defineConfig({
  testDir: resolve(__dirname, '../../tests/e2e/desktop'),
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  outputDir: resolve(__dirname, '../../artifacts/playwright'),
  reporter: process.env.CI ? [['list'], ['github']] : [['list']],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})
