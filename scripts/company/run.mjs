import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { delimiter, dirname, join, resolve } from 'node:path'
import { startLocalSandbox } from './sandbox-local.mjs'
import { startLocalReplyStream } from './reply-stream-local.mjs'
import { startLocalDatabase } from './database-local.mjs'
import { createInfra } from './local-infra/compose.mjs'
import { createLifecycle } from './local-infra/lifecycle.mjs'
import { directServiceEnvironment, signalOwnedChild } from './local-infra/processes.mjs'
const root = resolve(import.meta.dirname, '../..')
const webRequire = createRequire(join(root, 'apps/web/package.json'))
const python =
  process.env.PAA_SERVER_PYTHON ||
  join(root, '.venv-server', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const action = process.argv[2]
const env = {
  ...process.env,
  PYTHONPATH: [
    join(root, 'apps/server'),
    join(root, 'packages/voiceprint-engine/src'),
    process.env.PYTHONPATH,
  ]
    .filter(Boolean)
    .join(delimiter),
}
if (!existsSync(python)) {
  console.error('请先用 Python 3.12 创建 .venv-server，并安装 apps/server/requirements.lock。')
  process.exit(1)
}
const children = []
function launch(command, args, childEnv = env) {
  const child = spawn(command, args, {
    cwd: root,
    env: childEnv,
    stdio: 'inherit',
    detached: process.platform !== 'win32',
  })
  children.push(child)
  child.on('error', (error) => {
    console.error(error.message)
    stop(1)
  })
  child.on('exit', (code) => stop(code ?? 0))
  return child
}
let stopping = false
let lifecycle = null
let stopPromise
let startupPromise = Promise.resolve()
const startup = new AbortController()
function stop(code) {
  if (stopPromise) return stopPromise
  stopping = true
  startup.abort()
  process.exitCode = code
  stopPromise = (async () => {
    await Promise.all(
      children.map(
        (child) =>
          new Promise((accept) => {
            if (child.exitCode !== null || child.signalCode !== null || !child.pid) return accept()
            const timer = setTimeout(() => signalOwnedChild(child, 'SIGKILL'), 15_000)
            child.once('close', () => {
              clearTimeout(timer)
              accept()
            })
            signalOwnedChild(child, 'SIGTERM')
          }),
      ),
    )
    await startupPromise.catch(() => {})
    await lifecycle?.stop()
  })().catch((error) => {
    console.error(error.message)
    process.exitCode = 1
  })
  return stopPromise
}
process.on('SIGINT', () => {
  void stop(0)
})
process.on('SIGTERM', () => {
  void stop(0)
})
if (action === 'all') {
  startupPromise = (async () => {
    const infra = await createInfra()
    lifecycle = await createLifecycle(infra, { signal: startup.signal })
    await startLocalDatabase({ signal: startup.signal, infra, lifecycle })
    const reply = await startLocalReplyStream({ signal: startup.signal, infra, lifecycle })
    env.PAA_REPLY_STREAM_REDIS_URL = reply.url
    await startLocalSandbox({ signal: startup.signal, infra, lifecycle })
    startup.signal.throwIfAborted()
  })()
  try {
    await startupPromise
  } catch (error) {
    if (!stopping) console.error(error.message)
    await stop(stopping ? (process.exitCode ?? 0) : 1)
  }
}
if (!stopping && (action === 'all' || action === 'api'))
  launch(
    python,
    [
      '-m',
      'uvicorn',
      'app.main:app',
      '--host',
      '127.0.0.1',
      '--port',
      '8000',
      '--reload',
      '--reload-dir',
      join(root, 'apps/server'),
      '--reload-dir',
      join(root, 'packages/voiceprint-engine/src'),
    ],
    directServiceEnvironment(env),
  )
if (!stopping && (action === 'all' || action === 'worker'))
  launch(python, ['-m', 'app.worker'], directServiceEnvironment(env))
if (!stopping && action === 'all')
  launch(process.execPath, [
    join(dirname(webRequire.resolve('vite/package.json')), 'bin/vite.js'),
    '--config',
    'apps/web/vite.config.ts',
  ])
if (action === 'migrate' || action === 'bootstrap-admin' || action === 'model-key')
  launch(python, ['-m', 'app.cli', action])
if (action === 'test')
  launch(python, [join(root, 'scripts/company/test-server.py'), ...process.argv.slice(3)])
if (!['all', 'api', 'worker', 'migrate', 'bootstrap-admin', 'model-key', 'test'].includes(action)) {
  console.error('Unknown company command')
  process.exitCode = 1
}
