import { spawn } from 'node:child_process'

export function directServiceEnvironment(source) {
  const env = { ...source }
  for (const name of Object.keys(env))
    if (/^(https?|all|no|openai)_proxy$/i.test(name)) delete env[name]
  // Also prevent Python clients from falling back to macOS system proxies.
  return { ...env, NO_PROXY: '*', no_proxy: '*' }
}

export function signalOwnedChild(
  child,
  signal,
  { platform = process.platform, kill = process.kill.bind(process), launch = spawn } = {},
) {
  if (child.exitCode !== null || child.signalCode !== null || !child.pid) return
  if (platform === 'win32') {
    const command = launch(
      'taskkill',
      ['/PID', String(child.pid), '/T', ...(signal === 'SIGKILL' ? ['/F'] : [])],
      { stdio: 'ignore', windowsHide: true },
    )
    command.on('error', () => child.kill(signal))
    return
  }
  try {
    kill(-child.pid, signal)
  } catch (error) {
    if (error.code !== 'ESRCH') throw error
  }
}
