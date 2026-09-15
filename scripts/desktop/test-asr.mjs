import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { pythonCommand } from '../lib/python-command.mjs'
const root = resolve(import.meta.dirname, '../..')
process.chdir(root)
const { command, args } = pythonCommand(root)
const result = spawnSync(command, [...args, 'tests/core/real_asr_check.py'], { stdio: 'inherit' })
process.exit(result.status ?? 1)
