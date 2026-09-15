import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e/desktop',
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  outputDir: 'artifacts/playwright',
  reporter: process.env.CI ? [['list'], ['github']] : [['list']],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})
