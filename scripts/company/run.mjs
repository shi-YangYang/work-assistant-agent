import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { delimiter, dirname, join, resolve } from 'node:path'
import { startLocalSandbox } from './sandbox-local.mjs'
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
function launch(command, args) {
  const child = spawn(command, args, { cwd: root, env, stdio: 'inherit' })
  children.push(child)
  child.on('error', (error) => {
    console.error(error.message)
    stop(1)
  })
  child.on('exit', (code) => stop(code ?? 0))
  return child
}
let stopping = false
let sandbox = null
const startup = new AbortController()
function stop(code) {
  if (stopping) return
  stopping = true
  startup.abort()
  for (const child of children) child.kill('SIGTERM')
  process.exitCode = code
  if (sandbox)
    void sandbox.stop().catch((error) => {
      console.error(error.message)
      process.exitCode = 1
    })
}
process.on('SIGINT', () => stop(0))
process.on('SIGTERM', () => stop(0))
if (action === 'all') {
  try {
    sandbox = await startLocalSandbox({ signal: startup.signal })
  } catch (error) {
    if (!stopping) console.error(error.message)
    process.exitCode = stopping ? process.exitCode : 1
    stopping = true
  }
  if (stopping) process.exit(process.exitCode ?? 0)
}
if (action === 'all' || action === 'api')
  launch(python, [
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
  ])
if (action === 'all' || action === 'worker') launch(python, ['-m', 'app.worker'])
if (action === 'all')
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
