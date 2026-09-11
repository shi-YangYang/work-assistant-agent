import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
const [resourcesArgument] = process.argv
  .slice(2)
  .filter((argument) => argument !== '--licenses-only')
const resources = resolve(
  resourcesArgument ||
    (process.platform === 'darwin'
      ? 'dist/desktop/mac-arm64/个人工作助手.app/Contents/Resources'
      : 'dist/desktop/win-unpacked/resources'),
)
const executable = join(
  resources,
  'paa-core',
  process.platform === 'win32' ? 'paa-core.exe' : 'paa-core',
)
assert.ok(existsSync(executable), 'Build the actual desktop package before this check')
assert.ok(existsSync(join(resources, 'app.asar')))
const pythonLicense = join(resources, 'paa-core/licenses/Python-LICENSE.txt')
assert.ok(existsSync(pythonLicense), 'The packaged Python runtime license is missing')
assert.ok(
  readFileSync(pythonLicense, 'utf8').trim(),
  'The packaged Python runtime license is empty',
)
// The runtime lock is deliberately included for reproducibility, not a user's environment.
assert.equal(
  readFileSync(join(resources, 'licenses/requirements.lock'), 'utf8'),
  readFileSync('requirements.lock', 'utf8'),
)
if (process.argv.includes('--licenses-only')) {
  console.log(JSON.stringify({ pythonLicense: true, runtimeLock: true, resources }, null, 2))
  process.exit(0)
}
const fixture = resolve('artifacts/spec003/real-asr')
const models = join(fixture, 'models')
const directory = readdirSync(models).find((name) => existsSync(join(models, name, 'model.bin')))
assert.ok(directory, 'Prepare the existing public small-model fixture with npm run test:asr')
const temporary = mkdtempSync(join(tmpdir(), 'paa packaged 中文 '))
try {
  // Executable is absolute; no source cwd, venv, Python or Node executable is on child PATH.
  const env = {
    ...process.env,
    PATH: temporary,
    PAA_PYTHON: join(temporary, 'no-python'),
    PYTHONPATH: '',
    PYTHONHOME: '',
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
  }
  const checked = spawnSync(
    executable,
    [
      '--runtime-check',
      '--model-path',
      join(models, directory),
      '--audio-path',
      join(fixture, 'public-speech.wav'),
    ],
    { cwd: temporary, env, encoding: 'utf8', timeout: 180_000, windowsHide: true },
  )
  if (checked.status !== 0)
    throw new Error(`Frozen runtime failed: ${checked.error?.message || checked.stderr}`)
  const result = JSON.parse(checked.stdout.trim())
  assert.equal(result.frozen, true)
  const protocol = spawnSync(executable, ['--data-dir', join(temporary, 'data')], {
    cwd: temporary,
    env,
    encoding: 'utf8',
    timeout: 30_000,
    windowsHide: true,
    input: ['health', 'meetings.list', 'shutdown']
      .map((method, i) => JSON.stringify({ id: String(i), method }) + '\n')
      .join(''),
  })
  assert.equal(protocol.status, 0, protocol.stderr)
  const replies = protocol.stdout
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line))
  assert.equal(replies.length, 3)
  assert.match(replies[0].result.pythonVersion, /^3\.12\./)
  assert.deepEqual(replies[1].result.meetings, [])
  assert.equal(replies[2].result.stopping, true)
  mkdirSync('artifacts/spec005', { recursive: true })
  writeFileSync(
    `artifacts/spec005/package-${process.platform}-${process.arch}.json`,
    JSON.stringify({ ...result, protocol: true, resources, externalRuntimePath: false }, null, 2),
  )
  console.log(JSON.stringify({ ...result, protocol: true }, null, 2))
} finally {
  rmSync(temporary, { recursive: true, force: true })
}
