import { afterEach, expect, it, vi } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import desktopConfig, { defaultCompanyUrl } from '../../apps/desktop/electron.vite.config'

const roots: string[] = []
function directory(): string {
  vi.stubEnv('PAA_DESKTOP_COMPANY_URL', undefined)
  const root = mkdtempSync(join(tmpdir(), 'paa-desktop-build-'))
  roots.push(root)
  return root
}
afterEach(() => {
  vi.unstubAllEnvs()
  roots.splice(0).forEach((root) => rmSync(root, { recursive: true, force: true }))
})

it('does not use examples or company server configuration as desktop defaults', () => {
  const root = directory()
  writeFileSync(
    join(root, '.env.electron.example'),
    'PAA_DESKTOP_COMPANY_URL=https://example.invalid',
  )
  writeFileSync(
    join(root, '.env.web'),
    'PAA_WEB_ORIGIN=https://server.invalid\nPAA_DESKTOP_COMPANY_URL=https://wrong.invalid',
  )
  expect(defaultCompanyUrl(root)).toBe('')
})

it('reads the desktop dotenv file, normalizes the URL and permits an empty value', () => {
  const root = directory()
  writeFileSync(
    join(root, '.env.electron'),
    'PAA_DESKTOP_COMPANY_URL="https://desktop.example/"\nDATABASE_PASSWORD=private-test-marker',
  )
  expect(defaultCompanyUrl(root)).toBe('https://desktop.example')
  writeFileSync(join(root, '.env.electron'), 'PAA_DESKTOP_COMPANY_URL=')
  expect(defaultCompanyUrl(root)).toBe('')
})

it('ignores Vite mode files and honors explicit environment overrides', () => {
  const root = directory()
  writeFileSync(join(root, '.env.electron'), 'PAA_DESKTOP_COMPANY_URL=http://127.0.0.1:5174')
  writeFileSync(join(root, '.env.production'), 'PAA_DESKTOP_COMPANY_URL=https://release.example')
  expect(defaultCompanyUrl(root)).toBe('http://127.0.0.1:5174')
  vi.stubEnv('PAA_DESKTOP_COMPANY_URL', 'https://override.example')
  expect(defaultCompanyUrl(root)).toBe('https://override.example')
  vi.stubEnv('PAA_DESKTOP_COMPANY_URL', '')
  expect(defaultCompanyUrl(root)).toBe('')
})

it.each([
  'not-a-url',
  'http://public.example',
  'https://user:secret@example.com',
  'https://example.com/?key=secret',
  'https://example.com/path',
])('rejects invalid defaults without echoing their contents: %s', (url) => {
  const root = directory()
  writeFileSync(join(root, '.env.electron'), `PAA_DESKTOP_COMPANY_URL=${url}`)
  expect(() => defaultCompanyUrl(root)).toThrow(/^PAA_DESKTOP_COMPANY_URL 须为/)
})

it('injects only the public address into main, never the environment or renderer', async () => {
  vi.stubEnv('PAA_DESKTOP_COMPANY_URL', 'https://bundled.example')
  vi.stubEnv('PAA_AGENT_API_KEY', 'private-test-marker')
  if (typeof desktopConfig !== 'function') throw new Error('Expected a mode-aware config')
  const config = await desktopConfig({ command: 'build', mode: 'production' })
  expect(config.main?.define).toEqual({ __PAA_DESKTOP_COMPANY_URL__: '"https://bundled.example"' })
  expect(config.renderer?.define).toBeUndefined()
  expect(config.preload?.define).toBeUndefined()
  expect(JSON.stringify(config)).not.toContain('private-test-marker')
})
