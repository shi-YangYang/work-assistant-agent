import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'

export default defineConfig({
  testDir: resolve(__dirname, '../../tests/e2e/desktop'),
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  outputDir: process.env.PROJECT_TEST_OUTPUT
    ? resolve(process.env.PROJECT_TEST_OUTPUT, 'test-results')
    : resolve(__dirname, '../../artifacts/playwright'),
  reporter: process.env.PROJECT_TEST_OUTPUT
    ? [['list'], ['json', { outputFile: resolve(process.env.PROJECT_TEST_OUTPUT, 'results.json') }]]
    : process.env.CI
      ? [['list'], ['github']]
      : [['list']],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})
