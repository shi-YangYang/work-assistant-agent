import { spawnSync } from 'node:child_process'
import { pythonCommand } from './python-command.mjs'
const { command, args } = pythonCommand(process.cwd())
const result = spawnSync(
  command,
  [...args, '-m', 'pip', 'install', '-r', 'requirements-build.lock', '-c', 'requirements.lock'],
  { stdio: 'inherit' },
)
process.exit(result.status ?? 1)
