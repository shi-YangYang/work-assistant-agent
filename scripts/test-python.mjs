import { spawnSync } from 'node:child_process'
import { pythonCommand } from './python-command.mjs'

const { command, args } = pythonCommand(process.cwd())
const version = spawnSync(command, [
  ...args,
  '-c',
  'import sys; sys.exit(sys.version_info[:2] != (3, 12))',
])
if (version.error || version.status !== 0) {
  console.error('Python 3.12 is required. Create .venv or set PAA_PYTHON; see README.')
  process.exit(1)
}
const result = spawnSync(
  command,
  [...args, '-m', 'unittest', 'discover', '-s', 'tests/python', '-v'],
  {
    stdio: 'inherit',
  },
)
if (result.error) console.error('Unable to start Python tests.')
process.exit(result.status ?? 1)
