import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseEnv } from 'node:util'

export const root = resolve(import.meta.dirname, '../../..')
export const legacySandboxProject = `noria-sandbox-${createHash('sha256').update(root).digest('hex').slice(0, 10)}`
export const defaultStateDir = join(root, 'data/company/local-infra')

export async function readSettings() {
  const source = await readFile(join(root, 'apps/server/.env.web'), 'utf8').catch((error) => {
    if (error.code === 'ENOENT') throw new Error('请先配置 apps/server/.env.web。')
    throw error
  })
  return { source, values: { ...parseEnv(source), ...process.env } }
}

export function dockerCommand(
  args,
  env,
  { signal, capture = true, input, timeout = 180_000 } = {},
) {
  return new Promise((accept, reject) => {
    const child = spawn('docker', args, {
      cwd: root,
      env,
      signal,
      timeout,
      stdio: [input === undefined ? 'ignore' : 'pipe', capture ? 'pipe' : 'inherit', 'pipe'],
    })
    const chunks = []
    child.stdout?.on('data', (chunk) => chunks.push(chunk))
    child.stderr.resume()
    child.on('error', (error) =>
      reject(
        error.name === 'AbortError'
          ? error
          : new Error('Docker 无法执行，请确认 Docker 已安装并启动。', { cause: error }),
      ),
    )
    child.on('close', (code) => {
      if (code === 0) accept(Buffer.concat(chunks).toString().trim())
      else
        reject(
          new Error(
            `Docker ${args.slice(0, 2).join(' ')} 失败（${code ?? '已中断'}）。请检查该服务的 Docker 日志。`,
          ),
        )
    })
    if (input !== undefined) {
      child.stdin.on('error', () => {})
      child.stdin.end(input)
    }
  })
}

export async function createInfra({
  values,
  project,
  stateDir = process.env.PAA_LOCAL_STATE_DIR || defaultStateDir,
  command = dockerCommand,
  mapping,
} = {}) {
  values ??= (await readSettings()).values
  project ??= values.PAA_LOCAL_PROJECT || 'paa-company'
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(project)) throw new Error('本地 Compose 项目名无效。')
  if (mapping === undefined) {
    mapping = await readFile(join(stateDir, 'resources.json'), 'utf8').then(JSON.parse, (error) => {
      if (error.code === 'ENOENT') return null
      throw error
    })
  }
  if (mapping && mapping.project !== project)
    throw new Error('本地资源映射属于其他项目，请指定独立 PAA_LOCAL_STATE_DIR。')
  const journal = await readFile(join(stateDir, 'migration.json'), 'utf8').then(
    JSON.parse,
    (error) => {
      if (error.code === 'ENOENT') return null
      throw error
    },
  )
  if (journal?.phase === 'complete' && !mapping)
    throw new Error('迁移资源映射缺失，请恢复 local-infra 备份；不会初始化空数据库。')
  if (journal && journal.project !== project)
    throw new Error('迁移记录属于其他项目，请指定独立 PAA_LOCAL_STATE_DIR。')
  const address = new URL(
    values.DATABASE_URL || 'postgresql://paa:local@127.0.0.1:5432/paa_company',
  )
  const env = {
    ...process.env,
    ...values,
    POSTGRES_USER: values.POSTGRES_USER || decodeURIComponent(address.username) || 'paa',
    POSTGRES_DB:
      values.POSTGRES_DB || decodeURIComponent(address.pathname.slice(1)) || 'paa_company',
    POSTGRES_PASSWORD: values.POSTGRES_PASSWORD || decodeURIComponent(address.password) || 'local',
    LOCAL_SANDBOX_PROJECT: mapping?.imageProject || legacySandboxProject,
    PAA_LOCAL_PG_VOLUME:
      values.PAA_LOCAL_PG_VOLUME ||
      (project === 'paa-company' ? 'paa_company_pgdata' : `${project}_pgdata`),
  }
  const files = ['deploy/company/compose.dev.yml']
  if (values.PAA_SANDBOX_LOCAL === 'true') files.push('deploy/company/compose.sandbox-local.yml')
  if (mapping)
    files.push(
      join(
        stateDir,
        values.PAA_SANDBOX_LOCAL === 'true'
          ? 'resources.compose.json'
          : 'resources.business.compose.json',
      ),
    )
  const base = [
    'compose',
    '--progress',
    'plain',
    '-p',
    project,
    ...files.flatMap((file) => ['-f', file]),
  ]
  const docker = (args, options) => command(args, env, options)
  const inspect = async (name, options) => {
    try {
      return JSON.parse(await docker(['inspect', name], options))[0]
    } catch (error) {
      if (error.name === 'AbortError') throw error
      // Distinguish a missing container from a stopped daemon before creating anything.
      await docker(['info', '--format', '{{.OSType}}'], options)
      return null
    }
  }
  return {
    project,
    stateDir,
    values,
    env,
    base,
    mapping,
    journal,
    docker,
    inspect,
    compose: (args, options) => docker([...base, ...args], options),
    name: (service) => `${project}-${service}-1`,
  }
}

export async function rejectLegacy(infra, signal, services) {
  if (infra.journal && !['complete', 'rolled-back'].includes(infra.journal.phase))
    throw new Error('本地容器迁移尚未完成，请执行 npm run dev:web:migrate -- rollback 后再启动。')
  if (infra.mapping || infra.project !== 'paa-company') return
  const legacyNames = {
    postgres: 'paa-company-postgres',
    redis: 'paa-company-reply-redis',
    control: `${legacySandboxProject}-control-1`,
    runtime: `${legacySandboxProject}-runtime-1`,
  }
  for (const name of services.map((service) => legacyNames[service])) {
    if (await infra.inspect(name, { signal }))
      throw new Error(
        `发现旧本地容器 ${name}。请先退出开发服务，再执行 npm run dev:web:migrate；原数据不会被自动替换。`,
      )
  }
}
