import assert from 'node:assert/strict'
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'

async function run(mode, url = 'redis://127.0.0.1:6379/0') {
  const directory = await mkdtemp(join(tmpdir(), 'spec055-redis-launch-'))
  const log = join(directory, 'commands.jsonl')
  try {
    await writeFile(
      join(directory, 'docker'),
      `#!${process.execPath}
const fs = require('node:fs')
const args = process.argv.slice(2)
fs.appendFileSync(process.env.CONTROL_LOG, JSON.stringify(args) + '\\n')
const ownerFile = process.env.CONTROL_LOG + '.owner'
if (args[0] === 'inspect') {
  if (args[2].includes('Labels')) console.log(fs.existsSync(ownerFile) ? fs.readFileSync(ownerFile, 'utf8') : 'foreign-owner')
  else if (process.env.CONTROL_MODE === 'running') console.log('true')
  else if (process.env.CONTROL_MODE === 'stopped') console.log('false')
  else process.exitCode = 1
} else if (args[0] === 'run') {
  fs.writeFileSync(ownerFile, args[args.indexOf('--label') + 1].split('=')[1])
  if (process.env.CONTROL_MODE === 'failed') process.exitCode = 1
} else if (args[0] === 'exec') console.log('PONG')
`,
      { mode: 0o755 },
    )
    const source = `import {startLocalReplyStream} from ${JSON.stringify(resolve('scripts/company/reply-stream-local.mjs'))}; const value = await startLocalReplyStream(); await value.stop(); await value.stop();`
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', source], {
      env: {
        ...process.env,
        PATH: directory + ':' + process.env.PATH,
        CONTROL_LOG: log,
        CONTROL_MODE: mode,
        PAA_REPLY_STREAM_REDIS_URL: url,
      },
      encoding: 'utf8',
      timeout: 5000,
    })
    const commands = await readFile(log, 'utf8').then(
      (text) => text.trim().split('\n').map(JSON.parse),
      () => [],
    )
    return { result, commands }
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
}

test('local Redis reuses running services and stops only resources it started', async () => {
  for (const mode of ['running', 'stopped', 'new']) {
    const { result, commands } = await run(mode)
    assert.equal(result.status, 0, result.stderr)
    assert.equal(
      commands.filter(([command]) => command === 'stop').length,
      mode === 'running' ? 0 : 1,
    )
    if (mode === 'new') {
      const args = commands.find(([command]) => command === 'run')
      assert.ok(args.includes('64mb') && args.includes('noeviction') && args.includes('128m'))
      assert.ok(args.includes('127.0.0.1:6379:6379'))
    }
  }
})

test('startup failure cleans an owned container and external Redis is untouched', async () => {
  const failed = await run('failed')
  assert.notEqual(failed.result.status, 0)
  assert.equal(failed.commands.filter(([command]) => command === 'stop').length, 1)
  for (const url of [
    'redis://127.0.0.1:16379/0',
    'rediss://redis.example/0',
    'redis://user:private@localhost:6379/0',
  ]) {
    const external = await run('external', url)
    assert.equal(external.result.status, 0, external.result.stderr)
    assert.deepEqual(external.commands, [])
  }
})
