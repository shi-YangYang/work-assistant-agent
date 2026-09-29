import { defineConfig, devices } from '@playwright/test'
import { resolve } from 'node:path'

const run = process.env.SPEC044_RUN_ID ?? new Date().toISOString().replace(/[:.]/g, '-')
if (!/^[a-zA-Z0-9_-]+$/.test(run)) throw new Error('Invalid acceptance run ID')
const evidence = resolve(__dirname, '../../artifacts/spec044/browser', run)

export default defineConfig({
  testDir: resolve(__dirname, '../../tests/e2e/web'),
  outputDir: resolve(evidence, 'test-results'),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['json', { outputFile: resolve(evidence, 'results.json') }]],
  use: {
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    reducedMotion: 'reduce',
    screenshot: 'only-on-failure',
    trace: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } },
    },
    { name: 'firefox', grep: /@cross/, use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', grep: /@cross/, use: { ...devices['Desktop Safari'] } },
  ],
})
