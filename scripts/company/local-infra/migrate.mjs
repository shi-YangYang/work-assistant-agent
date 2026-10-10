import { randomUUID } from 'node:crypto'
import { mkdir, readFile, rm } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createInfra, legacySandboxProject, defaultStateDir, root } from './compose.mjs'
import { acquireLock } from './lifecycle.mjs'
import { usesLocalDatabase } from '../database-local.mjs'
import { replyStreamConfig } from '../reply-stream-local.mjs'
import { fingerprint } from '../sandbox-local.mjs'
import {
  saveJson,
  assertAppStopped,
  mountFor,
  assertDatabaseIdle,
  assertSandboxIdle,
  databaseDigest,
  backupDatabase,
  pgConfig,
  recreateArgs,
  validateMounts,
} from './migration-data.mjs'

function legacyNames(infra) {
  return {
    postgres: infra.values.PAA_LEGACY_POSTGRES || 'paa-company-postgres',
    redis: infra.values.PAA_LEGACY_REDIS || 'paa-company-reply-redis',
    runtime: `${infra.values.PAA_LEGACY_SANDBOX_PROJECT || legacySandboxProject}-runtime-1`,
    control: `${infra.values.PAA_LEGACY_SANDBOX_PROJECT || legacySandboxProject}-control-1`,
  }
}

export function makeMapping(infra, old, migrationId) {
  const services = {},
    volumes = {}
  const mount = (item, target, key) => {
    const entry = mountFor(item, target)
    if (entry.type === 'volume') {
      volumes[key] = { name: entry.source, external: true }
      return { type: 'volume', source: key, target }
    }
    return entry
  }
  if (old.postgres) {
    const config = pgConfig(old.postgres)
    services.postgres = {
      image: old.postgres.Image,
      environment: {
        POSTGRES_USER: config.user,
        POSTGRES_DB: config.database,
        POSTGRES_PASSWORD: config.password,
      },
      volumes: [mount(old.postgres, '/var/lib/postgresql/data', 'pgdata')],
      command: old.postgres.Config.Cmd,
    }
  }
  if (old.runtime)
    services.runtime = { volumes: [mount(old.runtime, '/var/lib/docker', 'engine-data')] }
  if (old.control) services.control = { volumes: [mount(old.control, '/state', 'control-state')] }
  if (migrationId)
    for (const service of Object.keys(old)) {
      services[service] ??= {}
      services[service].labels = { 'com.noria.local-migration': migrationId }
    }
  return { services, volumes }
}

function validateOld(infra, old) {
  for (const [service, item] of Object.entries(old)) {
    const labels = item.Config.Labels || {}
    if (['control', 'runtime'].includes(service)) {
      if (
        labels['com.docker.compose.project'] !==
          (infra.values.PAA_LEGACY_SANDBOX_PROJECT || legacySandboxProject) ||
        labels['com.docker.compose.service'] !== service
      )
        throw new Error(`旧 ${service} 容器归属不符，拒绝迁移。`)
    } else if (
      labels['com.docker.compose.project'] &&
      labels['com.docker.compose.project'] !== 'paa-company'
    ) {
      throw new Error(`旧 ${service} 容器属于其他 Compose 项目，拒绝迁移。`)
    }
    if (service === 'postgres' && !item.Config.Env.some((entry) => entry.startsWith('PG_MAJOR=')))
      throw new Error('旧数据库镜像不是可识别的 PostgreSQL。')
    if (service === 'redis' && !item.Config.Cmd?.includes('redis-server'))
      throw new Error('同名容器并非本地 Redis，拒绝迁移。')
    const port = {
      postgres: ['5432/tcp', infra.values.PAA_LOCAL_POSTGRES_PORT || '5432'],
      redis: ['6379/tcp', infra.values.PAA_LOCAL_REDIS_PORT || '6379'],
      control: ['8010/tcp', infra.values.PAA_SANDBOX_LOCAL_PORT || '8011'],
    }[service]
    if (
      port &&
      !item.HostConfig.PortBindings?.[port[0]]?.some(
        (entry) => entry.HostPort === String(port[1]) && ['127.0.0.1', ''].includes(entry.HostIp),
      )
    )
      throw new Error(`旧 ${service} 端口不匹配，拒绝迁移。`)
    const allowedMounts = {
      postgres: ['/var/lib/postgresql/data'],
      redis: ['/data'],
      runtime: ['/var/lib/docker', '/var/run'],
      control: ['/state', '/var/run'],
    }[service]
    if (
      item.Mounts.some((mount) => !allowedMounts.includes(mount.Destination)) ||
      item.HostConfig.Devices?.length
    )
      throw new Error(`旧 ${service} 有额外挂载或设备，不支持自动迁移。`)
    recreateArgs(item) // Validate that rollback can reproduce each original container before stopping it.
  }
  if (Boolean(old.control) !== Boolean(old.runtime))
    throw new Error('旧沙盒服务不完整，请先恢复旧沙盒或检查配置。')
}

export function isMigrationTarget(item, service, journal, project) {
  return (
    item.Config.Labels?.['com.docker.compose.project'] === project &&
    item.Config.Labels?.['com.docker.compose.service'] === service &&
    item.Config.Labels?.['com.noria.local-migration'] === journal.id &&
    (journal.targets?.[service]
      ? item.Id === journal.targets[service]
      : journal.startingService === service)
  )
}

export async function rollback(infra, journal) {
  const targets = []
  const originals = new Map()
  for (const service of ['control', 'runtime', 'redis', 'postgres']) {
    if (!journal.targets?.[service] && journal.startingService !== service) continue
    const item = await infra.inspect(infra.name(service))
    if (!item) continue
    if (!isMigrationTarget(item, service, journal, infra.project))
      throw new Error('迁移目标容器已被替换，停止自动回滚，原数据保留。')
    targets.push({ service, item })
  }
  for (const [service, original] of Object.entries(journal.old)) {
    const item = await infra.inspect(original.Name.slice(1))
    if (item && item.Id !== original.Id) throw new Error('旧容器名称已被占用，停止自动回滚。')
    originals.set(service, item)
  }
  // Check only the verified control containers, before any stop, remove or recreation.
  await assertSandboxIdle(infra, targets.find(({ service }) => service === 'control')?.item)
  await assertSandboxIdle(infra, originals.get('control'))
  for (const { item } of targets) {
    await infra.docker(['stop', '--time', '20', item.Id])
    await infra.docker(['rm', item.Id])
  }
  for (const service of ['postgres', 'redis', 'runtime', 'control']) {
    const original = journal.old[service]
    if (!original) continue
    let item = originals.get(service)
    if (!item) {
      await infra.docker(recreateArgs(original))
      item = await infra.inspect(original.Name.slice(1))
      original.Id = item.Id
    }
    if (original.State.Running) await infra.docker(['start', item.Id])
    else if (item.State.Running) await infra.docker(['stop', item.Id])
  }
  await rm(join(infra.stateDir, 'resources.json'), { force: true })
  await rm(join(infra.stateDir, 'resources.compose.json'), { force: true })
  await rm(join(infra.stateDir, 'resources.business.compose.json'), { force: true })
  journal.phase = 'rolled-back'
  await saveJson(join(infra.stateDir, 'migration.json'), journal)
}

export async function migrate({ infra, signal, fault } = {}) {
  infra ??= await createInfra()
  const release = await acquireLock(infra)
  let journal
  try {
    await assertAppStopped(infra)
    if (infra.journal?.phase === 'complete') {
      console.log('本地容器已完成统一，无需再次迁移。')
      return
    }
    if (infra.journal && !['rolled-back'].includes(infra.journal.phase))
      throw new Error('上次迁移未完成，请先运行 npm run dev:web:migrate -- rollback。')
    const old = {}
    for (const [service, name] of Object.entries(legacyNames(infra))) {
      if (service === 'postgres' && !usesLocalDatabase(infra.values)) continue
      if (service === 'redis' && !replyStreamConfig(infra.values).local) continue
      if (['control', 'runtime'].includes(service) && infra.values.PAA_SANDBOX_LOCAL !== 'true')
        continue
      const item = await infra.inspect(name, { signal })
      if (item) old[service] = item
      if (await infra.inspect(infra.name(service), { signal }))
        throw new Error('目标项目已有容器，请先核查，迁移不会覆盖现有项目。')
    }
    if (!Object.keys(old).length) {
      console.log('未发现旧容器，新环境可直接运行 npm run dev:web。')
      return
    }
    validateOld(infra, old)
    await validateMounts(infra, old)
    signal?.throwIfAborted()
    const backupDir = join(infra.stateDir, 'backup')
    await mkdir(backupDir, { recursive: true, mode: 0o700 })
    journal = { id: randomUUID(), phase: 'preflight', old, targets: {}, project: infra.project }
    await saveJson(join(infra.stateDir, 'migration.json'), journal)
    if (old.postgres) {
      if (!old.postgres.State.Running) {
        await infra.docker(['start', old.postgres.Id])
        for (let n = 0; n < 60; n++) {
          try {
            await assertDatabaseIdle(infra, old.postgres)
            break
          } catch (error) {
            if (n === 59) throw error
            await new Promise((accept) => setTimeout(accept, 500))
          }
        }
      }
      await assertDatabaseIdle(infra, old.postgres)
      journal.database = await databaseDigest(infra, old.postgres)
      console.log('正在备份数据库，并在隔离容器中恢复核对…')
      await backupDatabase(infra, old.postgres, backupDir)
    }
    signal?.throwIfAborted()
    if (old.postgres) await assertDatabaseIdle(infra, old.postgres)
    await assertSandboxIdle(infra, old.control)
    journal.phase = 'stopping'
    await saveJson(join(infra.stateDir, 'migration.json'), journal)
    for (const service of ['control', 'runtime', 'redis', 'postgres'])
      if (old[service]) await infra.docker(['stop', '--time', '20', old[service].Id])
    if (old.control)
      await infra.docker(['cp', `${old.control.Id}:/state/.`, join(backupDir, 'control-state')])
    signal?.throwIfAborted()
    if (fault === 'after-stop') throw new Error('测试注入：停止旧服务后失败。')
    const oldBuild = await readFile(
      join(root, 'data/company/sandbox-local/build.sha256'),
      'utf8',
    ).catch(() => '')
    const mapping = {
      project: infra.project,
      imageProject: legacySandboxProject,
      ...(oldBuild === (await fingerprint({ legacyLayout: true }))
        ? { sandboxFingerprint: await fingerprint() }
        : {}),
    }
    const overrides = makeMapping(infra, old, journal.id)
    await saveJson(join(infra.stateDir, 'resources.compose.json'), overrides)
    await saveJson(join(infra.stateDir, 'resources.business.compose.json'), {
      services: Object.fromEntries(
        Object.entries(overrides.services).filter(([service]) =>
          ['postgres', 'redis'].includes(service),
        ),
      ),
      volumes: overrides.volumes.pgdata ? { pgdata: overrides.volumes.pgdata } : {},
    })
    await saveJson(join(infra.stateDir, 'resources.json'), mapping)
    const next = await createInfra({
      values: { ...infra.values, ...(old.runtime ? { PAA_SANDBOX_LOCAL: 'true' } : {}) },
      project: infra.project,
      stateDir: infra.stateDir,
      mapping,
    })
    journal.phase = 'starting'
    await saveJson(join(infra.stateDir, 'migration.json'), journal)
    for (const service of ['postgres', 'redis', 'runtime', 'control']) {
      if (!old[service]) continue
      journal.startingService = service
      await saveJson(join(infra.stateDir, 'migration.json'), journal)
      try {
        await next.compose(
          ['up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '90', service],
          {
            signal,
            timeout: 120_000,
          },
        )
      } finally {
        const created = await next.inspect(next.name(service))
        if (created && isMigrationTarget(created, service, journal, infra.project))
          journal.targets[service] = created.Id
        await saveJson(join(infra.stateDir, 'migration.json'), journal)
      }
      if (service === 'postgres') {
        const after = await next.inspect(next.name(service))
        if (
          after.Image !== old.postgres.Image ||
          JSON.stringify(await databaseDigest(next, after)) !== JSON.stringify(journal.database)
        )
          throw new Error('迁移后数据库镜像或数据核对不一致。')
      }
    }
    signal?.throwIfAborted()
    if (fault === 'after-start') throw new Error('测试注入：新服务启动后失败。')
    journal.phase = 'verified'
    await saveJson(join(infra.stateDir, 'migration.json'), journal)
    for (const item of Object.values(old)) await infra.docker(['rm', item.Id])
    journal.phase = 'complete'
    await saveJson(join(infra.stateDir, 'migration.json'), journal)
    console.log('本地容器已统一到一个 Compose 项目；原数据卷、镜像和迁移备份已保留。')
  } catch (error) {
    if (journal) {
      console.error('迁移未完成，正在恢复旧环境…')
      try {
        await rollback(infra, journal)
      } catch (rollbackError) {
        throw new AggregateError(
          [error, rollbackError],
          '迁移及自动回滚未完成，请保留 local-infra 目录并执行 rollback。',
        )
      }
    }
    throw error
  } finally {
    await release()
  }
}

async function main() {
  const stateDir = process.env.PAA_LOCAL_STATE_DIR || defaultStateDir
  const infra = await createInfra({ stateDir })
  const controller = new AbortController()
  process.once('SIGINT', () => controller.abort())
  process.once('SIGTERM', () => controller.abort())
  if (process.argv[2] === 'rollback') {
    const release = await acquireLock(infra)
    try {
      await assertAppStopped(infra)
      if (!infra.journal) throw new Error('未找到迁移记录。')
      const pg = await infra.inspect(infra.name('postgres'))
      if (pg?.State.Running) await assertDatabaseIdle(infra, pg)
      await rollback(infra, infra.journal)
      console.log('已恢复旧容器拓扑，数据保留。')
    } finally {
      await release()
    }
  } else if (!process.argv[2]) await migrate({ infra, signal: controller.signal })
  else throw new Error('Usage: migrate.mjs [rollback]')
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href)
  main().catch((error) => {
    console.error(error.message)
    process.exitCode = 1
  })
