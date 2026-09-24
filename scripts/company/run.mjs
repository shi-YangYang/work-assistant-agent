import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { delimiter, dirname, join, resolve } from 'node:path'
const root = resolve(import.meta.dirname, '../..')
const webRequire = createRequire(join(root, 'apps/web/package.json'))
const python =
  process.env.PAA_SERVER_PYTHON ||
  join(root, '.venv-server', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const action = process.argv[2]
const env = {
  ...process.env,
  PYTHONPATH: [
    join(root, 'apps/server/src'),
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
function stop(code) {
  if (stopping) return
  stopping = true
  for (const child of children) child.kill('SIGTERM')
  process.exitCode = code
}
process.on('SIGINT', () => stop(0))
process.on('SIGTERM', () => stop(0))
if (action === 'all' || action === 'api')
  launch(python, [
    '-m',
    'uvicorn',
    'paa_server.api:app',
    '--host',
    '127.0.0.1',
    '--port',
    '8000',
    '--reload',
    '--reload-dir',
    join(root, 'apps/server/src'),
    '--reload-dir',
    join(root, 'packages/voiceprint-engine/src'),
  ])
if (action === 'all' || action === 'worker') launch(python, ['-m', 'paa_server.worker'])
if (action === 'all')
  launch(process.execPath, [
    join(dirname(webRequire.resolve('vite/package.json')), 'bin/vite.js'),
    '--config',
    'apps/web/vite.config.ts',
  ])
if (action === 'migrate' || action === 'bootstrap-admin' || action === 'model-key')
  launch(python, ['-m', 'paa_server.cli', action])
if (action === 'test')
  launch(python, [
    '-m',
    'pytest',
    '-q',
    ...(process.argv.length > 3 ? process.argv.slice(3) : ['tests/server']),
  ])
if (!['all', 'api', 'worker', 'migrate', 'bootstrap-admin', 'model-key', 'test'].includes(action)) {
  console.error('Unknown company command')
  process.exitCode = 1
}
