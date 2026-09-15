import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { pythonCommand } from '../lib/python-command.mjs'
const root = resolve(import.meta.dirname, '../..')
process.chdir(root)
const { command, args } = pythonCommand(root)
const result = spawnSync(
  command,
  [
    ...args,
    '-m',
    'pip',
    'install',
    '-r',
    'apps/desktop/core/requirements-build.lock',
    '-c',
    'apps/desktop/core/requirements.lock',
  ],
  { stdio: 'inherit' },
)
process.exit(result.status ?? 1)
