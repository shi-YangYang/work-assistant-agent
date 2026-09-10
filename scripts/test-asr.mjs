import { spawnSync } from 'node:child_process'
import { pythonCommand } from './python-command.mjs'
const { command, args } = pythonCommand(process.cwd())
const result = spawnSync(command, [...args, 'tests/python/real_asr_check.py'], { stdio: 'inherit' })
process.exit(result.status ?? 1)
