import { test } from 'node:test'
import assert from 'node:assert/strict'
import { outcome, summarizeNative } from '../../scripts/testing/project-tests.mjs'
test('exit failure, incomplete collection, zero discoveries and required skip cannot pass', () => {
  assert.equal(outcome(1, { complete: true, cases: [{ status: 'passed' }] }), 'failed')
  assert.equal(outcome(0), 'blocked')
  assert.equal(outcome(0, { complete: true, cases: [] }), 'blocked')
  assert.equal(outcome(0, { complete: false, cases: [{ status: 'passed' }] }), 'blocked')
  assert.equal(outcome(0, { complete: true, cases: [{ status: 'skipped' }] }), 'failed')
})
test('Playwright expected failure and retries are not counted as passing', () => {
  const parsed = summarizeNative(
    {
      suites: [
        {
          specs: [
            {
              file: 'a',
              line: 1,
              title: 'case',
              tests: [
                {
                  projectName: 'chromium',
                  expectedStatus: 'failed',
                  results: [{ status: 'failed' }],
                },
              ],
            },
          ],
        },
      ],
    },
    'playwright',
  )
  assert.equal(outcome(0, parsed), 'failed')
})
test('Vitest retains failures and stable case IDs', () => {
  const parsed = summarizeNative(
    {
      success: true,
      testResults: [{ name: 'a', assertionResults: [{ fullName: 'ok', status: 'passed' }] }],
    },
    'vitest',
  )
  assert.equal(outcome(0, parsed), 'passed')
  assert.equal(parsed.cases[0].id, 'a:ok')
})
