import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  cpSync,
  rmSync,
  readdirSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync, spawn } from 'node:child_process'

function fixture(command, timeoutMs = 3000) {
  const root = mkdtempSync(join(tmpdir(), 'project-runner-contract-'))
  mkdirSync(join(root, 'scripts/testing'), { recursive: true })
  mkdirSync(join(root, 'tests'))
  for (const name of ['project-tests.mjs', 'redis-environment.py'])
    cpSync('scripts/testing/' + name, join(root, 'scripts/testing', name))
  writeFileSync(
    join(root, 'tests/suites.json'),
    JSON.stringify({
      suites: { tiny: ['tiny'] },
      groups: { tiny: { command, timeoutMs, reporter: 'normalized' } },
    }),
  )
  execFileSync('git', ['init', '-q'], { cwd: root })
  // A disposable repository lets the real CLI capture source identity without touching this checkout.
  execFileSync(
    'git',
    [
      '-c',
      'user.name=Test',
      '-c',
      'user.email=test@example.invalid',
      'commit',
      '-q',
      '--allow-empty',
      '-m',
      'test: 合成运行器夹具',
    ],
    { cwd: root },
  )
  return root
}
async function run(root, cancel = false) {
  const child = spawn(process.execPath, ['scripts/testing/project-tests.mjs', '--suite', 'tiny'], {
    cwd: root,
    stdio: 'ignore',
  })
  const timer = cancel ? setTimeout(() => child.kill('SIGINT'), 300) : null
  const code = await new Promise((resolve) => child.on('close', resolve))
  clearTimeout(timer)
  const runs = join(root, 'artifacts/project-tests')
  const id = readdirSync(runs).sort().at(-1)
  return { code, summary: JSON.parse(readFileSync(join(runs, id, 'summary.json'))) }
}
test('real CLI retains missing executable failure and hashes newly added source', async () => {
  const root = fixture(['project-command-that-does-not-exist'])
  try {
    const first = await run(root)
    assert.notEqual(first.code, 0)
    assert.equal(first.summary.groups[0].status, 'blocked')
    writeFileSync(join(root, 'new-source.txt'), 'new source content')
    const second = await run(root)
    assert.notEqual(first.summary.source.workspaceHash, second.summary.source.workspaceHash)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
test('real CLI timeout and SIGINT terminate the owned process and preserve non-pass results', async () => {
  for (const cancel of [false, true]) {
    const root = fixture([process.execPath, '-e', 'setInterval(()=>{},100)'], 500)
    try {
      const result = await run(root, cancel)
      assert.notEqual(result.code, 0)
      assert.notEqual(result.summary.status, 'passed')
      assert.notEqual(result.summary.groups[0].exit.signal, null)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  }
})

test(
  'uncooperative process is force-reaped within the shutdown bound',
  { timeout: 22000 },
  async () => {
    const root = fixture(
      [
        process.execPath,
        '-e',
        "require('fs').writeFileSync(require('path').join(process.env.PROJECT_TEST_OUTPUT,'pid'),String(process.pid));process.on('SIGTERM',()=>{});setInterval(()=>{},100)",
      ],
      500,
    )
    try {
      const result = await run(root)
      assert.equal(result.summary.status, 'failed')
      assert.equal(result.summary.groups[0].exit.signal, 'SIGKILL')
      const pid = Number(
        readFileSync(join(root, 'artifacts/project-tests', result.summary.runId, 'tiny/pid')),
      )
      assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' })
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  },
)

test(
  'leader exit cannot cancel descendant reclamation or permit early cleanup',
  { timeout: 25000 },
  async () => {
    const descendant =
      "process.on('SIGTERM',()=>{});require('fs').writeFileSync(process.env.PROJECT_TEST_OUTPUT+'/descendant',String(process.pid));setInterval(()=>{},100)"
    const root = fixture(
      [
        process.execPath,
        '-e',
        `const fs=require('fs'); const cp=require('child_process'); cp.spawn(process.execPath,['-e',${JSON.stringify(descendant)}],{stdio:'ignore'});fs.writeFileSync(process.env.PROJECT_TEST_OUTPUT+'/environment.json',JSON.stringify({cleaned:false})); process.on('SIGTERM',()=>process.exit(0));setInterval(()=>{},100)`,
      ],
      800,
    )
    mkdirSync(join(root, '.venv-server/bin'), { recursive: true })
    // A cleanup sentinel inspects the actual descendant before reporting success.
    const cleanup = join(root, '.venv-server/bin/python')
    writeFileSync(
      cleanup,
      `#!${process.execPath}\nconst fs=require('fs');const p=process.env.PROJECT_TEST_OUTPUT;try{process.kill(Number(fs.readFileSync(p+'/descendant')),0);process.exit(9)}catch(e){if(e.code!=='ESRCH')throw e}fs.writeFileSync(p+'/cleanup-after-reap','yes')\n`,
      { mode: 0o755 },
    )
    try {
      const result = await run(root)
      assert.equal(result.summary.status, 'failed')
      const output = join(root, 'artifacts/project-tests', result.summary.runId, 'tiny')
      assert.equal(readFileSync(join(output, 'cleanup-after-reap'), 'utf8'), 'yes')
      assert.throws(() => process.kill(Number(readFileSync(join(output, 'descendant'))), 0), {
        code: 'ESRCH',
      })
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  },
)

test('runner clears inherited daily Redis target and namespace', async () => {
  const root = fixture([
    process.execPath,
    '-e',
    "const e=process.env;require('fs').writeFileSync(e.PROJECT_TEST_OUTPUT+'/results.json',JSON.stringify({complete:true,cases:[{id:'redis',status:e.PAA_REPLY_STREAM_REDIS_URL===''&&e.PAA_REPLY_STREAM_NAMESPACE.startsWith('project:test:')?'passed':'failed'}]}))",
  ])
  const old = { ...process.env }
  try {
    delete process.env.PAA_REPLY_STREAM_TEST_URL
    process.env.PAA_REPLY_STREAM_REDIS_URL = 'redis://unowned.invalid:6379/0'
    process.env.PAA_REPLY_STREAM_NAMESPACE = 'daily'
    assert.equal((await run(root)).summary.status, 'passed')
  } finally {
    process.env = old
    rmSync(root, { recursive: true, force: true })
  }
})

test(
  'direct wrapper owns its group and leaves an unrelated service alive',
  { timeout: 23000 },
  async () => {
    const root = fixture([])
    const shared = spawn(process.execPath, ['-e', 'setInterval(()=>{},100)'], {
      detached: true,
      stdio: 'ignore',
    })
    const script = `require('child_process').spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});require('fs').writeFileSync(process.env.PROJECT_TEST_OUTPUT+'/pid',String(process.pid));setInterval(()=>{},100)"],{stdio:'ignore'});setTimeout(()=>process.exit(0),500)`
    try {
      const child = spawn(
        process.execPath,
        ['scripts/testing/project-tests.mjs', '--owned-wrapper', process.execPath, '-e', script],
        { cwd: root, env: { ...process.env, PROJECT_TEST_OUTPUT: root }, stdio: 'ignore' },
      )
      const code = await new Promise((resolve) => child.once('close', resolve))
      assert.equal(code, 0)
      assert.throws(() => process.kill(Number(readFileSync(join(root, 'pid'))), 0), {
        code: 'ESRCH',
      })
      assert.equal(process.kill(shared.pid, 0), true)
    } finally {
      shared.kill('SIGKILL')
      rmSync(root, { recursive: true, force: true })
    }
  },
)
