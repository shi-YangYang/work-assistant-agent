import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
const yaml = readFileSync('.github/workflows/ci.yml', 'utf8')
const source = yaml
  .split("node <<'JS'\n")[1]
  .split('\n          JS')[0]
  .replace(/^ {10}/gm, '')
function check(checks, desktop, integration, mutate = () => {}) {
  const jobs = {
    checks: { result: checks ? 'success' : 'skipped' },
    desktop: { result: desktop ? 'success' : 'skipped' },
    integration: { result: integration ? 'success' : 'skipped' },
  }
  mutate(jobs)
  return spawnSync(process.execPath, ['-e', source], {
    env: {
      ...process.env,
      CHECK_RESULTS: JSON.stringify(jobs),
      EVENT_NAME: 'workflow_dispatch',
      SELECTED_CHECKS: checks ? 'quick' : desktop ? 'desktop' : integration ? 'asr' : 'invalid',
      SELECTED_PLATFORM: 'macos-15',
      CHECKS_REQUIRED: String(checks),
      DESKTOP_REQUIRED: String(desktop),
      INTEGRATION_REQUIRED: String(integration),
    },
  }).status
}
test('PR/tag/manual quick and each manual platform stage require exactly their selected jobs', () => {
  for (const selected of [
    [true, false, false],
    [false, true, false],
    [false, false, true],
  ]) {
    assert.equal(check(...selected), 0)
    const required = ['checks', 'desktop', 'integration'][selected.indexOf(true)]
    for (const result of ['failure', 'cancelled', 'skipped', undefined])
      assert.notEqual(
        check(...selected, (jobs) => {
          jobs[required] = { result }
        }),
        0,
      )
    assert.notEqual(
      check(...selected, (jobs) => {
        delete jobs[required]
      }),
      0,
    )
  }
})

test('unrecognized selection cannot pass all-skipped aggregate', () => {
  assert.notEqual(check(false, false, false), 0)
})
