// Explicit Docker rehearsal: all resources use disposable names, volumes and ports.
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createInfra } from '../../scripts/company/local-infra/compose.mjs'
import { createLifecycle } from '../../scripts/company/local-infra/lifecycle.mjs'
import { migrate, rollback } from '../../scripts/company/local-infra/migrate.mjs'
import { pgQuery, databaseDigest } from '../../scripts/company/local-infra/migration-data.mjs'

if (process.env.PAA_RUN_DOCKER_REHEARSAL !== '1')
  throw new Error('Set PAA_RUN_DOCKER_REHEARSAL=1 to run isolated Docker tests.')
const project = `noria-rehearsal-${process.pid}`
const stateDir = await mkdtemp(join(tmpdir(), `${project}-`))
const values = {
  PAA_LOCAL_POSTGRES_PORT: '15447',
  PAA_LOCAL_REDIS_PORT: '16397',
  PAA_LOCAL_API_PORT: '18010',
  PAA_LOCAL_WEB_PORT: '18014',
  PAA_LOCAL_PG_VOLUME: `${project}-data`,
  DATABASE_URL: 'postgresql://paa:controlled@127.0.0.1:15447/rehearsal',
  PAA_REPLY_STREAM_REDIS_URL: 'redis://127.0.0.1:16397/0',
  PAA_LEGACY_POSTGRES: `${project}-legacy-pg`,
  PAA_LEGACY_REDIS: `${project}-legacy-redis`,
  POSTGRES_PASSWORD: 'controlled',
  PAA_SANDBOX_LOCAL: 'false',
}
const infra = await createInfra({ values, project, stateDir })
const evidence = []
let failed
try {
  await infra.docker([
    'run',
    '-d',
    '--name',
    values.PAA_LEGACY_POSTGRES,
    '-p',
    '127.0.0.1:15447:5432',
    '-e',
    'POSTGRES_USER=paa',
    '-e',
    'POSTGRES_DB=rehearsal',
    '-e',
    'POSTGRES_PASSWORD=controlled',
    '--mount',
    `type=volume,source=${values.PAA_LOCAL_PG_VOLUME},target=/var/lib/postgresql/data`,
    'postgres:17.11-bookworm',
  ])
  await infra.docker([
    'run',
    '-d',
    '--name',
    values.PAA_LEGACY_REDIS,
    '-p',
    '127.0.0.1:16397:6379',
    'redis:7.4.2-alpine',
    'redis-server',
    '--save',
    '',
    '--appendonly',
    'no',
  ])
  const before = await infra.inspect(values.PAA_LEGACY_POSTGRES)
  for (let n = 0; n < 60; n++) {
    try {
      await pgQuery(infra, before, 'SELECT 1')
      break
    } catch (error) {
      if (n === 59) throw error
      await new Promise((accept) => setTimeout(accept, 500))
    }
  }
  await pgQuery(
    infra,
    before,
    "CREATE TABLE company_job(id integer primary key, state text); INSERT INTO company_job VALUES (1,'awaiting_input'),(2,'awaiting_retry'); CREATE TABLE records(kind text primary key, data jsonb); INSERT INTO records SELECT kind, jsonb_build_object('content','中文资料','version',2) FROM unnest(ARRAY['account','conversation','work','memory','artifact']) kind;",
  )
  const digest = await databaseDigest(infra, before)
  await assert.rejects(migrate({ infra, fault: 'after-stop' }), /测试注入/)
  assert.deepEqual(
    await databaseDigest(infra, await infra.inspect(values.PAA_LEGACY_POSTGRES)),
    digest,
  )
  evidence.push('Injected stop-stage failure rolled back and preserved all seeded records')
  let next = await createInfra({ values, project, stateDir })
  await assert.rejects(migrate({ infra: next, fault: 'after-start' }), /测试注入/)
  assert.deepEqual(
    await databaseDigest(infra, await infra.inspect(values.PAA_LEGACY_POSTGRES)),
    digest,
  )
  evidence.push('Injected post-start failure rolled back without simultaneous volume writers')
  next = await createInfra({ values, project, stateDir })
  await migrate({ infra: next })
  next = await createInfra({ values, project, stateDir })
  assert.equal((await next.inspect(next.name('postgres'))).Image, before.Image)
  assert.equal(await next.inspect(values.PAA_LEGACY_POSTGRES), null)
  assert.deepEqual(await databaseDigest(next, await next.inspect(next.name('postgres'))), digest)
  await migrate({ infra: next })
  evidence.push(
    'Successful migration and repeat invocation preserved exact image, volume and records',
  )
  await rollback(next, next.journal)
  assert.deepEqual(
    await databaseDigest(infra, await infra.inspect(values.PAA_LEGACY_POSTGRES)),
    digest,
  )
  evidence.push(
    'Explicit rollback recreated removed legacy shells from recorded image/security configuration',
  )
  await migrate({ infra: await createInfra({ values, project, stateDir }) })
  next = await createInfra({ values, project, stateDir })
  await next.compose(['stop', 'redis'])
  const times = []
  for (let n = 0; n < 3; n++) {
    const start = performance.now()
    const lifecycle = await createLifecycle(next)
    await lifecycle.start('postgres')
    await lifecycle.start('redis')
    assert.equal(await next.docker(['exec', next.name('redis'), 'redis-cli', 'ping']), 'PONG')
    await assert.rejects(createLifecycle(next), /已有本地/)
    await lifecycle.stop()
    assert.equal((await next.inspect(next.name('postgres'))).State.Running, true)
    assert.equal((await next.inspect(next.name('redis'))).State.Running, false)
    times.push(Math.round(performance.now() - start))
  }
  evidence.push({ threeStartStopCyclesMs: times })
  await next.compose(['start', 'redis'])
  assert.equal(await next.docker(['exec', next.name('redis'), 'redis-cli', 'ping']), 'PONG')
  evidence.push('Independent Redis restart recovered PONG while PostgreSQL stayed running')
  const redis = await next.inspect(next.name('redis'))
  assert.equal(redis.Config.Labels['com.docker.compose.project'], project)
} catch (error) {
  failed = error
} finally {
  // Never issue global cleanup; only these exact disposable resources are removable.
  for (const name of [
    values.PAA_LEGACY_POSTGRES,
    values.PAA_LEGACY_REDIS,
    `${project}-restore-check`,
    infra.name('postgres'),
    infra.name('redis'),
  ])
    if (await infra.inspect(name)) await infra.docker(['rm', '-f', name])
  await infra.docker(['volume', 'rm', values.PAA_LOCAL_PG_VOLUME]).catch(() => {})
  await infra.docker(['network', 'rm', `${project}_business`]).catch(() => {})
  const destination = join('artifacts', 'spec057')
  await mkdir(destination, { recursive: true })
  await writeFile(
    join(destination, 'docker-migration-rehearsal.json'),
    JSON.stringify({ project, evidence, error: failed?.message }, null, 2),
  )
  await rm(stateDir, { recursive: true, force: true })
}
if (failed) throw failed
console.log(JSON.stringify(evidence, null, 2))
