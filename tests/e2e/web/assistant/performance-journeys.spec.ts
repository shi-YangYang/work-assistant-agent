import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

// Explicit opt-in only: the driver validates disposable-schema ownership before login.
// A sample supplies frozen inputs and output paths, never model keys or daily accounts.
test('frozen Agent journey measures complete browser delivery and actual artifacts', async ({
  browserName,
}, info) => {
  test.skip(browserName !== 'chromium', 'The frozen timing environment uses Chromium')
  test.skip(
    !process.env.SPEC056_SAMPLE,
    'Requires an explicitly owned real-model performance sample',
  )
  test.setTimeout(30 * 60_000)
  const options = JSON.parse(readFileSync(resolve(process.env.SPEC056_SAMPLE!), 'utf8'))
  // Invoke the same native ESM driver used for real sampling. Playwright's test
  // transform runs these specs as CommonJS and cannot import its import.meta.
  await promisify(execFile)(process.execPath, [
    resolve('scripts/benchmarks/assistant-latency-browser.mjs'),
    ...Object.entries(options).flatMap(([key, value]) => [`--${key}`, String(value)]),
  ])
  const rows = readFileSync(resolve(options.output, 'results.jsonl'), 'utf8')
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line))
  await info.attach('performance-results.json', {
    body: JSON.stringify(rows, null, 2),
    contentType: 'application/json',
  })
  expect(rows.length).toBeGreaterThan(0)
  for (const row of rows) {
    expect(row.exception, `Measurement failed for ${row.case}`).toBeUndefined()
    expect(row.metrics.admittedSeconds).toBeGreaterThan(0)
    if (row.message?.reply) {
      expect(row.metrics.browserCompletePaintSeconds).toBeGreaterThan(0)
      expect(row.browserText.length).toBeGreaterThan(0)
    }
    for (const file of row.fileChecks ?? []) {
      expect(file.status).toBe(200)
      expect(file.size).toBeGreaterThan(0)
    }
  }
  // Semantic quality is assessed against the frozen task rubric separately;
  // rendering success must never be reported as answer correctness.
})
