import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { delimiter, join, resolve } from 'node:path'
const root = resolve(import.meta.dirname, '..')
const python =
  process.env.PAA_SERVER_PYTHON ||
  join(root, '.venv-server', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const action = process.argv[2]
const env = {
  ...process.env,
  PYTHONPATH: [join(root, 'src/python'), process.env.PYTHONPATH].filter(Boolean).join(delimiter),
}
if (!existsSync(python)) {
  console.error('请先用 Python 3.12 创建 .venv-server，并安装 requirements-server.lock。')
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
if (action === 'all' || action === 'api') launch(python, ['-m', 'paa_server.api'])
if (action === 'all' || action === 'worker') launch(python, ['-m', 'paa_server.worker'])
if (action === 'all')
  launch(process.execPath, [
    join(root, 'node_modules/vite/bin/vite.js'),
    '--config',
    'web.vite.config.ts',
  ])
if (action === 'migrate' || action === 'bootstrap-admin')
  launch(python, ['-m', 'paa_server.cli', action])
if (action === 'test')
  launch(python, [
    '-m',
    'pytest',
    '-q',
    ...(process.argv.length > 3 ? process.argv.slice(3) : ['tests/server']),
  ])
if (!['all', 'api', 'worker', 'migrate', 'bootstrap-admin', 'test'].includes(action)) {
  console.error('Unknown company command')
  process.exitCode = 1
}
