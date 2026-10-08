import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { parseEnv } from 'node:util'
import { setTimeout } from 'node:timers/promises'

const root = resolve(import.meta.dirname, '../..')
const name = 'paa-company-reply-redis'
function docker(args, signal) {
  return new Promise((accept, reject) => {
    const child = spawn('docker', args, { cwd: root, signal, stdio: ['ignore', 'pipe', 'pipe'] })
    let output = ''
    child.stdout.on('data', (chunk) => (output += chunk))
    child.stderr.resume()
    child.on('error', reject)
    child.on('close', (code) => accept({ code, output: output.trim() }))
  })
}

export async function startLocalReplyStream({ signal } = {}) {
  const source = parseEnv(
    await readFile(resolve(root, 'apps/server/.env.web'), 'utf8').catch((error) => {
      if (error.code === 'ENOENT') return ''
      throw error
    }),
  )
  const url =
    process.env.PAA_REPLY_STREAM_REDIS_URL ||
    source.PAA_REPLY_STREAM_REDIS_URL ||
    'redis://127.0.0.1:6379/0'
  const address = new URL(url)
  if (
    address.protocol !== 'redis:' ||
    address.username ||
    address.password ||
    !['127.0.0.1', 'localhost'].includes(address.hostname) ||
    (address.port && address.port !== '6379')
  )
    return { url, stop: async () => {} }
  let owned = false
  let created = false
  const owner = randomUUID()
  const stop = async () => {
    if (owned) {
      owned = false
      if (created) {
        const label = await docker([
          'inspect',
          '--format',
          '{{index .Config.Labels "paa.reply-owner"}}',
          name,
        ])
        if (label.output !== owner) return
      }
      await docker(['stop', name])
    }
  }
  try {
    signal?.throwIfAborted()
    const existing = await docker(['inspect', '--format', '{{.State.Running}}', name], signal)
    if (existing.code === 0) {
      if (existing.output !== 'true') {
        owned = true
        if ((await docker(['start', name], signal)).code !== 0)
          throw new Error('本地 Redis 启动失败。')
      }
    } else {
      owned = created = true
      const result = await docker(
        [
          'run',
          '--name',
          name,
          '--label',
          `paa.reply-owner=${owner}`,
          '-d',
          '-p',
          '127.0.0.1:6379:6379',
          '--memory',
          '128m',
          'redis:7.4.2-alpine',
          'redis-server',
          '--save',
          '',
          '--appendonly',
          'no',
          '--maxmemory',
          '64mb',
          '--maxmemory-policy',
          'noeviction',
        ],
        signal,
      )
      if (result.code !== 0) throw new Error('本地 Redis 启动失败，请检查 Docker 和 6379 端口。')
    }
    const deadline = Date.now() + 30_000
    while ((await docker(['exec', name, 'redis-cli', 'ping'], signal)).output !== 'PONG') {
      signal?.throwIfAborted()
      if (Date.now() >= deadline) throw new Error('等待本地 Redis 就绪超时。')
      await setTimeout(200, undefined, { signal })
    }
    signal?.throwIfAborted()
    console.log('本地正文流 Redis 已就绪。')
    return { url, stop }
  } catch (error) {
    await stop()
    throw error
  }
}
