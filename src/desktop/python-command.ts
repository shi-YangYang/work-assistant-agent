import { existsSync } from 'node:fs'
import { join } from 'node:path'

export function pythonCommand(
  root: string,
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): { command: string; args: string[] } {
  if (env.PAA_PYTHON?.trim()) return { command: env.PAA_PYTHON, args: [] }
  const virtualenv = join(root, '.venv', platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
  if (existsSync(virtualenv)) return { command: virtualenv, args: [] }
  return platform === 'win32'
    ? { command: 'py', args: ['-3.12'] }
    : { command: 'python3', args: [] }
}

export function coreLaunch(
  root: string,
  dataRoot: string,
  resourcesPath?: string,
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): { command: string; args: string[]; cwd: string } {
  if (resourcesPath) {
    const directory = join(resourcesPath, 'paa-core')
    return {
      command: join(directory, platform === 'win32' ? 'paa-core.exe' : 'paa-core'),
      args: ['--data-dir', dataRoot],
      cwd: directory,
    }
  }
  const python = pythonCommand(root, env, platform)
  return {
    command: python.command,
    args: [
      ...python.args,
      '-u',
      join(root, 'src/python/paa_core/__main__.py'),
      '--data-dir',
      dataRoot,
    ],
    cwd: root,
  }
}
