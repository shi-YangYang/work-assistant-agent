import { execFileSync } from 'node:child_process'
import { appendFileSync, readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

// Keep the always-on checks independent of this selection. Only expensive suites are gated.
export function selectChecks(paths, mode = 'auto') {
  if (!['auto', 'full', 'asr', 'package'].includes(mode)) throw new Error('Unknown CI mode')
  if (paths === null || mode === 'full') return { asr: true, package: true }
  const infrastructure = paths.some((path) =>
    /^(\.github\/|(?:package(?:-lock)?\.json|pnpm-lock\.yaml|requirements(?:-build)?\.lock|pyproject\.toml|tsconfig\.[^/]+\.json|playwright\.config\.ts)$|scripts\/ci-scope\.mjs$|tests\/desktop\/ci-scope\.test\.ts$)/.test(
      path,
    ),
  )
  return {
    asr:
      infrastructure ||
      mode === 'asr' ||
      paths.some((path) =>
        /^(src\/python\/paa_core\/(?:asr_worker|model_manager|transcription|transcript_store|audio_store|recorder|repository|protocol|__main__|__init__)\.py$|src\/renderer\/Transcription\.tsx$|src\/shared\/|scripts\/(?:test-asr|install-python|python-command)\.mjs$|tests\/python\/(?:real_asr_check|test_transcription|test_recording)\.py$|tests\/smoke\/transcription\.spec\.ts$)/.test(
          path,
        ),
      ),
    package:
      infrastructure ||
      mode === 'package' ||
      paths.some((path) =>
        /^(src\/(?:desktop|python|shared)\/|build\/|electron[^/]*\.(?:json|ts)$|scripts\/(?:build-core|install-build-python|install-python|python-command|test-package)\.mjs$|scripts\/(?:core-licenses\.py|licenses\/)|tests\/smoke\/package\.spec\.ts$)/.test(
          path,
        ),
      ),
  }
}

export function changedPaths(eventName, event, git) {
  if (eventName === 'workflow_dispatch') return []
  let range
  if (eventName === 'pull_request') {
    range = `${event.pull_request.base.sha}...${event.pull_request.head.sha}`
  } else if (eventName === 'push' && !/^0+$/.test(event.before || '0')) {
    range = `${event.before}..${event.after}`
  } else {
    // A new branch/tag has no previous tree. Run all suites instead of silently skipping.
    return null
  }
  try {
    // --no-renames includes both old and new paths; -z preserves spaces and Unicode.
    return git(['diff', '--name-only', '--no-renames', '-z', range, '--'])
      .split('\0')
      .filter(Boolean)
  } catch {
    return null // Missing history is not evidence that a suite is unnecessary.
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'))
  const paths = changedPaths(process.env.GITHUB_EVENT_NAME, event, (args) =>
    execFileSync('git', args, { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }),
  )
  const mode = process.env.GITHUB_REF?.startsWith('refs/tags/')
    ? 'full'
    : event.inputs?.checks || 'auto'
  const checks = selectChecks(paths, mode)
  appendFileSync(
    process.env.GITHUB_OUTPUT,
    Object.entries(checks)
      .map(([name, enabled]) => `${name}=${enabled}\n`)
      .join(''),
  )
  const summary = `CI scope: mode=${mode}, changed files=${paths?.length ?? 'unknown'}, ASR=${checks.asr}, package=${checks.package}`
  console.log(summary)
  if (process.env.GITHUB_STEP_SUMMARY)
    appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`)
}
