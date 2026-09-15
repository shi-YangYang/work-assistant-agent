import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { pythonCommand } from '../lib/python-command.mjs'

const root = resolve(import.meta.dirname, '../..')
process.chdir(root)
const { command, args } = pythonCommand(root)
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
  [
    ...args,
    '-c',
    [
      'import faulthandler, unittest',
      'faulthandler.dump_traceback_later(120, exit=True)',
      "unittest.main(module=None, argv=['unittest', 'discover', '-s', 'tests/core', '-v'])",
    ].join('\n'),
  ],
  {
    stdio: 'inherit',
    timeout: 150_000,
    killSignal: 'SIGKILL',
  },
)
if (result.error) console.error(`Python tests could not complete: ${result.error.message}`)
process.exit(result.status ?? 1)
