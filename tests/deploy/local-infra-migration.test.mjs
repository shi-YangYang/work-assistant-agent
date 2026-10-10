import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { makeMapping, rollback } from '../../scripts/company/local-infra/migrate.mjs'
import {
  mountFor,
  recreateArgs,
  assertDatabaseIdle,
} from '../../scripts/company/local-infra/migration-data.mjs'

function pg() {
  return {
    Name: '/legacy-postgres',
    Id: 'old',
    Image: 'sha256:original',
    Config: {
      Env: ['POSTGRES_USER=paa', 'POSTGRES_DB=test', 'POSTGRES_PASSWORD=controlled'],
      Cmd: ['postgres'],
      Labels: {},
    },
    HostConfig: {
      PortBindings: {},
      RestartPolicy: { Name: 'unless-stopped' },
      SecurityOpt: ['no-new-privileges:true'],
      CapDrop: ['NET_RAW'],
    },
    NetworkSettings: { Networks: { bridge: {} } },
    Mounts: [
      { Type: 'volume', Name: 'original-data', Destination: '/var/lib/postgresql/data', RW: true },
    ],
  }
}

test('migration pins the exact database image and original external volume without carrying business credentials into sandbox', () => {
  const result = makeMapping({}, { postgres: pg() })
  assert.equal(result.services.postgres.image, 'sha256:original')
  assert.deepEqual(result.volumes.pgdata, { name: 'original-data', external: true })
  assert.ok(!result.services.control)
})

test('bind mounts never create absent source directories; unsupported mounts fail closed', () => {
  const container = pg()
  container.Mounts[0] = { ...container.Mounts[0], Type: 'bind', Source: '/known/data' }
  assert.equal(mountFor(container, '/var/lib/postgresql/data').bind.create_host_path, false)
  container.Mounts[0].Type = 'tmpfs'
  assert.throws(() => mountFor(container, '/var/lib/postgresql/data'), /不受支持/)
})

test('rollback retains restart policy and security options as well as data/image identity', () => {
  const args = recreateArgs(pg())
  for (const value of [
    'unless-stopped',
    'no-new-privileges:true',
    'NET_RAW',
    'sha256:original',
    'type=volume,source=original-data,target=/var/lib/postgresql/data',
  ])
    assert.ok(args.includes(value))
})

test('migration rejects active application connections or jobs but does not treat awaiting_input as in-flight', async () => {
  const commands = []
  const infra = {
    docker: async (args) => {
      commands.push(args)
      return args.at(-1).includes('pg_stat_activity')
        ? '0'
        : args.at(-1).includes('to_regclass')
          ? 't'
          : '0'
    },
  }
  await assertDatabaseIdle(infra, pg())
  assert.ok(commands.at(-1).at(-1).includes("('queued','running')"))
  await assert.rejects(assertDatabaseIdle({ docker: async () => '1' }, pg()), /应用连接/)
})

test('rollback refuses unrelated services, replaced IDs and mismatched migration labels', async () => {
  const { isMigrationTarget } = await import('../../scripts/company/local-infra/migrate.mjs')
  const journal = { id: 'migration-1', targets: { redis: 'expected-id' }, startingService: 'redis' }
  const item = {
    Id: 'expected-id',
    Config: {
      Labels: {
        'com.docker.compose.project': 'test',
        'com.docker.compose.service': 'redis',
        'com.noria.local-migration': 'migration-1',
      },
    },
  }
  assert.equal(isMigrationTarget(item, 'redis', journal, 'test'), true)
  assert.equal(isMigrationTarget({ ...item, Id: 'replacement' }, 'redis', journal, 'test'), false)
  assert.equal(isMigrationTarget(item, 'postgres', journal, 'test'), false)
  assert.equal(isMigrationTarget(item, 'redis', { ...journal, id: 'different' }, 'test'), false)
})

test('rollback rejects busy or unreadable sandbox receipts before any mutation and never reads an unrelated control', async () => {
  const stateDir = await mkdtemp(join(tmpdir(), 'noria-rollback-test-'))
  const calls = []
  const control = {
    Id: 'control-id',
    State: { Running: true },
    Config: {
      Labels: {
        'com.docker.compose.project': 'test',
        'com.docker.compose.service': 'control',
        'com.noria.local-migration': 'migration-1',
      },
    },
  }
  const journal = { id: 'migration-1', old: {}, targets: { control: 'control-id' } }
  let result = '1'
  const infra = {
    project: 'test',
    stateDir,
    name: (service) => service,
    inspect: async () => control,
    docker: async (args) => {
      calls.push(args)
      if (result instanceof Error) throw result
      return result
    },
  }
  try {
    for (result of ['1', 'invalid output', new Error('receipt read failed')]) {
      calls.length = 0
      await assert.rejects(rollback(infra, journal), /执行中的任务|无法核对|receipt read failed/)
      assert.deepEqual(
        calls.map((args) => args[0]),
        ['exec'],
      )
      assert.equal(calls[0][1], 'control-id')
      assert.equal(control.State.Running, true)
    }
    calls.length = 0
    control.Id = 'unrelated-replacement'
    await assert.rejects(rollback(infra, journal), /已被替换/)
    assert.equal(calls.length, 0)
  } finally {
    await rm(stateDir, { recursive: true, force: true })
  }
})
