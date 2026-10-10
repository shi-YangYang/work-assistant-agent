import { connect } from 'node:net'
import { writeFile, rename, mkdir, stat } from 'node:fs/promises'
import { join } from 'node:path'

export async function saveJson(path, data) {
  await writeFile(`${path}.tmp`, JSON.stringify(data, null, 2) + '\n', { mode: 0o600 })
  await rename(`${path}.tmp`, path)
}

export async function assertAppStopped(infra) {
  const ports = [infra.values.PAA_LOCAL_API_PORT || 8000, infra.values.PAA_LOCAL_WEB_PORT || 5174]
  for (const port of ports) {
    const open = await new Promise((accept) => {
      const socket = connect({ host: '127.0.0.1', port: Number(port) })
      const finish = (value) => {
        socket.destroy()
        accept(value)
      }
      socket.once('connect', () => finish(true))
      socket.once('error', () => finish(false))
      socket.setTimeout(1000, () => finish(false))
    })
    if (open) throw new Error(`端口 ${port} 仍在使用，请先退出 API、worker 和 Web 开发命令。`)
  }
}

export function mountFor(container, target) {
  const mount = container.Mounts.find((entry) => entry.Destination === target)
  if (!mount || !['volume', 'bind'].includes(mount.Type) || !mount.RW)
    throw new Error(`容器 ${container.Name} 的 ${target} 挂载不受支持，原环境未被替换。`)
  return {
    type: mount.Type,
    source: mount.Type === 'volume' ? mount.Name : mount.Source,
    target,
    ...(mount.Type === 'bind' ? { bind: { create_host_path: false } } : {}),
  }
}

export async function validateMounts(infra, old) {
  const allowed = new Set(Object.values(old).map((item) => item.Id))
  for (const item of Object.values(old))
    for (const mount of item.Mounts) {
      if (mount.Type === 'bind') {
        if (!(await stat(mount.Source)).isDirectory()) throw new Error('旧挂载不是有效目录。')
      } else if (mount.Type === 'volume') await infra.docker(['volume', 'inspect', mount.Name])
      else throw new Error('存在不支持的旧挂载，请手动核查。')
      const writers = await infra.docker([
        'ps',
        '-q',
        '--no-trunc',
        '--filter',
        `volume=${mount.Type === 'volume' ? mount.Name : mount.Source}`,
      ])
      if (
        writers
          .split('\n')
          .filter(Boolean)
          .some((id) => !allowed.has(id))
      )
        throw new Error('旧持久卷还被其他运行中的容器使用，迁移已取消。')
    }
}

export function pgConfig(container) {
  const values = Object.fromEntries(
    container.Config.Env.map((value) => {
      const index = value.indexOf('=')
      return [value.slice(0, index), value.slice(index + 1)]
    }),
  )
  return {
    user: values.POSTGRES_USER || 'postgres',
    database: values.POSTGRES_DB || values.POSTGRES_USER || 'postgres',
    password: values.POSTGRES_PASSWORD,
  }
}

export function pgQuery(infra, container, sql) {
  const config = pgConfig(container)
  return infra.docker([
    'exec',
    container.Id,
    'psql',
    '-X',
    '-A',
    '-t',
    '-v',
    'ON_ERROR_STOP=1',
    '-U',
    config.user,
    '-d',
    config.database,
    '-c',
    sql,
  ])
}

export async function assertDatabaseIdle(infra, container) {
  const clients = await pgQuery(
    infra,
    container,
    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'",
  )
  if (Number(clients)) throw new Error('数据库仍有应用连接，请先退出 API 和 worker。')
  if (
    (await pgQuery(infra, container, "SELECT to_regclass('public.company_job') IS NOT NULL")) ===
    't'
  ) {
    if (
      Number(
        await pgQuery(
          infra,
          container,
          "SELECT count(*) FROM company_job WHERE state IN ('queued','running')",
        ),
      )
    )
      throw new Error('仍有排队或执行中的任务，迁移已取消；请等待任务完成。')
  }
}

export async function assertSandboxIdle(infra, container) {
  if (!container?.State.Running) return
  const pending = await infra.docker([
    'exec',
    container.Id,
    'python',
    '-c',
    `import json,pathlib; print(sum(json.loads(p.read_text()).get('state') in ('queued','running') for p in pathlib.Path('/state').glob('*/receipt.json')))`,
  ])
  if (!/^\d+$/.test(pending.trim())) throw new Error('无法核对沙盒执行状态，环境未被停止。')
  if (Number(pending)) throw new Error('沙盒仍有执行中的任务，请等待完成后再迁移或回滚。')
}

export async function databaseDigest(infra, container) {
  const tables = await pgQuery(
    infra,
    container,
    "SELECT quote_ident(schemaname)||'.'||quote_ident(tablename) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1",
  )
  const result = {}
  for (const table of tables.split('\n').filter(Boolean))
    result[table] = await pgQuery(
      infra,
      container,
      `SELECT count(*)||':'||md5(COALESCE(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) FROM ${table} t`,
    )
  return result
}

export async function backupDatabase(infra, container, backupDir) {
  const config = pgConfig(container)
  const dump = await infra.docker([
    'exec',
    container.Id,
    'pg_dump',
    '-U',
    config.user,
    '-d',
    config.database,
    '--no-owner',
    '--no-acl',
  ])
  await mkdir(backupDir, { recursive: true, mode: 0o700 })
  await writeFile(join(backupDir, 'database.sql'), dump + '\n', { mode: 0o600 })
  const verifier = `${infra.project}-restore-check`
  if (await infra.inspect(verifier))
    throw new Error(`备份验证容器 ${verifier} 已存在，请核查上次迁移。`)
  try {
    await infra.docker([
      'run',
      '-d',
      '--name',
      verifier,
      '--network',
      'none',
      '--tmpfs',
      '/var/lib/postgresql/data',
      '-e',
      `POSTGRES_USER=${config.user}`,
      '-e',
      `POSTGRES_DB=${config.database}`,
      '-e',
      'POSTGRES_HOST_AUTH_METHOD=trust',
      container.Image,
    ])
    let ready = false
    for (let attempt = 0; attempt < 60; attempt++) {
      try {
        await infra.docker([
          'exec',
          verifier,
          'pg_isready',
          '-U',
          config.user,
          '-d',
          config.database,
        ])
        ready = true
        break
      } catch {
        await new Promise((accept) => setTimeout(accept, 500))
      }
    }
    if (!ready) throw new Error('数据库备份恢复验证未就绪。')
    await infra.docker(
      [
        'exec',
        '-i',
        verifier,
        'psql',
        '-X',
        '-v',
        'ON_ERROR_STOP=1',
        '-U',
        config.user,
        '-d',
        config.database,
      ],
      { input: dump },
    )
    const restored = await infra.inspect(verifier)
    if (
      JSON.stringify(await databaseDigest(infra, restored)) !==
      JSON.stringify(await databaseDigest(infra, container))
    )
      throw new Error('数据库备份恢复后数据不一致。')
  } finally {
    await infra.docker(['rm', '-f', verifier])
  }
}

export function recreateArgs(item) {
  const args = ['create', '--name', item.Name.slice(1)]
  for (const [key, value] of Object.entries(item.Config.Labels || {}))
    args.push('--label', `${key}=${value}`)
  for (const value of item.Config.Env || []) args.push('-e', value)
  for (const mount of item.Mounts)
    args.push(
      '--mount',
      `type=${mount.Type},source=${mount.Type === 'volume' ? mount.Name : mount.Source},target=${mount.Destination}${mount.RW ? '' : ',readonly'}`,
    )
  for (const [port, bindings] of Object.entries(item.HostConfig.PortBindings || {}))
    for (const binding of bindings || [])
      args.push('-p', `${binding.HostIp || '127.0.0.1'}:${binding.HostPort}:${port}`)
  const host = item.HostConfig
  if (host.RestartPolicy?.Name && host.RestartPolicy.Name !== 'no')
    args.push(
      '--restart',
      host.RestartPolicy.Name +
        (host.RestartPolicy.MaximumRetryCount ? `:${host.RestartPolicy.MaximumRetryCount}` : ''),
    )
  for (const value of host.SecurityOpt || []) args.push('--security-opt', value)
  for (const value of host.CapAdd || []) args.push('--cap-add', value)
  for (const value of host.CapDrop || []) args.push('--cap-drop', value)
  if (host.Privileged) args.push('--privileged')
  if (host.ReadonlyRootfs) args.push('--read-only')
  if (host.Memory) args.push('--memory', String(host.Memory))
  if (host.MemorySwap) args.push('--memory-swap', String(host.MemorySwap))
  if (host.NanoCpus) args.push('--cpus', String(host.NanoCpus / 1e9))
  if (host.PidsLimit > 0) args.push('--pids-limit', String(host.PidsLimit))
  for (const [target, options] of Object.entries(host.Tmpfs || {}))
    args.push('--tmpfs', `${target}:${options}`)
  const networks = Object.keys(item.NetworkSettings.Networks)
  if (networks.length > 1) throw new Error('旧容器连接了多个网络，不支持自动重建。')
  if (networks[0]) args.push('--network', networks[0])
  if (item.Config.User) args.push('--user', item.Config.User)
  if (item.Config.WorkingDir) args.push('--workdir', item.Config.WorkingDir)
  const health = item.Config.Healthcheck
  if (health?.Test?.[0] === 'CMD-SHELL') args.push('--health-cmd', health.Test[1])
  if (health?.Test?.[0] === 'CMD')
    args.push(
      '--health-cmd',
      health.Test.slice(1)
        .map((part) => `'${part.replaceAll("'", "'\\''")}'`)
        .join(' '),
    )
  for (const [key, flag] of [
    ['Interval', '--health-interval'],
    ['Timeout', '--health-timeout'],
    ['StartPeriod', '--health-start-period'],
  ])
    if (health?.[key]) args.push(flag, `${health[key]}ns`)
  if (health?.Retries) args.push('--health-retries', String(health.Retries))
  const entrypoint = item.Config.Entrypoint || []
  if (entrypoint.length) args.push('--entrypoint', entrypoint[0])
  args.push(item.Image, ...entrypoint.slice(1), ...(item.Config.Cmd || []))
  return args
}
