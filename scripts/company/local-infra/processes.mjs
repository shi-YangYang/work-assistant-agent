import { spawn } from 'node:child_process'

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
