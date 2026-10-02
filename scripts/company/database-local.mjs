import { spawn } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseEnv } from 'node:util'
import { setTimeout } from 'node:timers/promises'

const root = resolve(import.meta.dirname, '../..')
const envFile = 'apps/server/.env.web'
const container = 'paa-company-postgres'

function docker(args, env, signal, capture = true) {
  return new Promise((accept, reject) => {
    const child = spawn('docker', args, {
      cwd: root,
      env,
      signal,
      stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
    })
    let output = ''
    if (capture) {
      child.stdout.on('data', (chunk) => (output += chunk))
      child.stderr.resume()
    }
    child.on('error', (error) =>
      reject(
        error.name === 'AbortError'
          ? error
          : new Error('无法启动本地数据库，请确认已安装并启动 Docker。'),
      ),
    )
    child.on('close', (code) => accept({ code, output }))
  })
}

export async function startLocalDatabase({ signal } = {}) {
  signal?.throwIfAborted()
  let source
  try {
    source = await readFile(join(root, envFile), 'utf8')
  } catch {
    throw new Error('请先配置 apps/server/.env.web，再启动 Web。')
  }
  const values = { ...parseEnv(source), ...process.env }
  let address
  try {
    address = new URL(values.DATABASE_URL || 'postgresql://paa:local@127.0.0.1:5432/paa_company')
  } catch {
    throw new Error('DATABASE_URL 格式无效，请检查 apps/server/.env.web。')
  }
  // Only manage the endpoint exposed by compose.dev.yml; other databases remain external.
  if (
    !['127.0.0.1', 'localhost'].includes(address.hostname) ||
    (address.port && address.port !== '5432') ||
    address.searchParams.has('host') ||
    address.searchParams.has('port')
  ) {
    console.log('使用已配置的外部数据库，跳过本地数据库容器启动。')
    return
  }
  signal?.throwIfAborted()
  const env = {
    ...process.env,
    POSTGRES_USER: values.POSTGRES_USER || decodeURIComponent(address.username) || 'paa',
    POSTGRES_DB:
      values.POSTGRES_DB || decodeURIComponent(address.pathname.slice(1)) || 'paa_company',
    POSTGRES_PASSWORD: values.POSTGRES_PASSWORD || decodeURIComponent(address.password),
  }
  console.log('正在启动本地数据库并等待就绪…')
  const existing = await docker(
    ['inspect', '--format', '{{json .State.Running}}|{{json .HostConfig.PortBindings}}', container],
    env,
    signal,
  )
  if (existing.code === 0) {
    const [running, bindings] = existing.output.trim().split('|').map(JSON.parse)
    if (!bindings?.['5432/tcp']?.some((binding) => binding.HostPort === '5432'))
      throw new Error('已有数据库容器未映射 5432 端口，请检查容器配置。')
    // Older local installations used docker run; reuse them without replacing their data.
    if (!running && (await docker(['start', container], env, signal, false)).code !== 0)
      throw new Error('数据库容器启动失败，请检查 Docker 和 5432 端口占用。')
    const deadline = Date.now() + 60_000
    while (true) {
      signal?.throwIfAborted()
      const ready = await docker(
        [
          'exec',
          container,
          'pg_isready',
          '-q',
          '-h',
          '127.0.0.1',
          '-t',
          '2',
          '-U',
          env.POSTGRES_USER,
          '-d',
          env.POSTGRES_DB,
        ],
        env,
        signal,
      )
      if (ready.code === 0) break
      if (Date.now() >= deadline)
        throw new Error('等待数据库就绪超时，请检查 paa-company-postgres 容器日志。')
      await setTimeout(500, undefined, { signal })
    }
  } else {
    const result = await docker(
      [
        'compose',
        '--env-file',
        envFile,
        '-f',
        'deploy/company/compose.dev.yml',
        'up',
        '-d',
        '--no-recreate',
        '--wait',
        '--wait-timeout',
        '60',
        'postgres',
      ],
      env,
      signal,
      false,
    )
    if (result.code !== 0)
      throw new Error('本地数据库未就绪，请检查 Docker、5432 端口和上方数据库日志。')
  }
  signal?.throwIfAborted()
  console.log('本地数据库已就绪：127.0.0.1:5432')
}
