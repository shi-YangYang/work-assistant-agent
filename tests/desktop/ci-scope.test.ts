import { describe, expect, it } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
// The same dependency-free entry point runs before npm ci in GitHub Actions.
// @ts-expect-error Project scripts are plain JavaScript, outside the TypeScript build.
import { changedPaths, selectChecks } from '../../scripts/ci-scope.mjs'

describe('expensive CI suite selection', () => {
  it.each([
    [['README.md', 'src/renderer/App.tsx', 'src/renderer/styles.css'], false, false],
    [['src/renderer/Transcription.tsx'], true, false],
    [['tests/python/test_transcription.py'], true, false],
    [['src/python/paa_core/model_manager.py'], true, true],
    [['src/desktop/main.ts'], false, true],
    [['build/core/paa-core.spec'], false, true],
    [['tests/smoke/package.spec.ts'], false, true],
    [['package-lock.json'], true, true],
    [['requirements.lock'], true, true],
    [['.github/workflows/ci.yml'], true, true],
    [['scripts/ci-scope.mjs'], true, true],
  ])('selects %j → ASR %s, package %s', (paths, asr, pkg) => {
    expect(selectChecks(paths)).toEqual({ asr, package: pkg })
  })

  it('supports manual suites and fails safe when the comparison is unavailable', () => {
    expect(selectChecks([], 'full')).toEqual({ asr: true, package: true })
    expect(selectChecks([], 'asr')).toEqual({ asr: true, package: false })
    expect(selectChecks([], 'package')).toEqual({ asr: false, package: true })
    expect(selectChecks(null)).toEqual({ asr: true, package: true })
    expect(changedPaths('push', { before: '000000', after: 'abc' })).toBeNull()
    expect(
      changedPaths('push', { before: 'abc', after: 'def' }, () => {
        throw new Error('History unavailable')
      }),
    ).toBeNull()
  })

  it('uses the full PR diff and retains deleted/renamed paths with real Git history', () => {
    const root = mkdtempSync(join(tmpdir(), 'paa-ci-scope-'))
    const git = (args: string[]) => execFileSync('git', args, { cwd: root, encoding: 'utf8' })
    const commit = (message: string) => {
      git(['add', '.'])
      git([
        '-c',
        'user.name=CI test',
        '-c',
        'user.email=ci@example.invalid',
        '-c',
        'commit.gpgsign=false',
        'commit',
        '-m',
        message,
      ])
      return git(['rev-parse', 'HEAD']).trim()
    }
    try {
      git(['init', '-q'])
      mkdirSync(join(root, 'src/python/paa_core'), { recursive: true })
      writeFileSync(join(root, 'src/python/paa_core/model_manager.py'), 'old model\n')
      const base = commit('baseline')
      git(['mv', 'src/python/paa_core/model_manager.py', '已移除 模型.txt'])
      const previous = commit('remove model implementation')
      writeFileSync(join(root, 'README.md'), 'documentation follow-up\n')
      const head = commit('docs')
      const pushed = changedPaths('push', { before: previous, after: head }, git)
      expect(selectChecks(pushed)).toEqual({ asr: false, package: false })
      const pr = changedPaths(
        'pull_request',
        { pull_request: { base: { sha: base }, head: { sha: head } } },
        git,
      )
      expect(pr).toContain('src/python/paa_core/model_manager.py')
      expect(pr).toContain('已移除 模型.txt')
      expect(selectChecks(pr)).toEqual({ asr: true, package: true })
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})
