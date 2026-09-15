import { existsSync } from 'node:fs'
import { join } from 'node:path'

// A single executable, never a shell command. Explicit overrides fail visibly.
export function pythonCommand(root, env = process.env, platform = process.platform) {
  if (env.PAA_PYTHON?.trim()) return { command: env.PAA_PYTHON, args: [] }
  const virtualenv = join(root, '.venv', platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
  if (existsSync(virtualenv)) return { command: virtualenv, args: [] }
  return platform === 'win32'
    ? { command: 'py', args: ['-3.12'] }
    : { command: 'python3', args: [] }
}
