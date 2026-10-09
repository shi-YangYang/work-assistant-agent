import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import {
  createLifecycle,
  acquireLock,
  assertReusableSandbox,
} from '../../scripts/company/local-infra/lifecycle.mjs'
import { createInfra, rejectLegacy } from '../../scripts/company/local-infra/compose.mjs'
import { usesLocalDatabase } from '../../scripts/company/database-local.mjs'

export async function fakeInfra(callback, { running = [], fail } = {}) {
  const stateDir = await mkdtemp(join(tmpdir(), 'noria-infra-test-'))
  const containers = new Map(),
    calls = []
  const project = 'isolated-test'
  const item = (service, active = true) => ({
    Id: `${service}-id`,
    Image: `${service}-config-id`,
    State: { Running: active },
    Config: {
      Labels: {
        'com.docker.compose.project': project,
        'com.docker.compose.service': service,
        'com.docker.compose.config-hash': `${service}-hash`,
      },
    },
  })
  for (const service of running) containers.set(service, item(service))
  const infra = {
    project,
    stateDir,
    values: {},
    name: (service) => service,
    inspect: async (service) => containers.get(service),
    docker: async () => 'same configuration and layers',
    compose: async (args) => {
      calls.push(args)
      const service = args.at(-1)
      if (args[0] === 'config')
        return args.includes('--hash')
          ? `${service} ${service}-hash`
          : JSON.stringify({
              services: { runtime: { image: 'runtime:dev' }, control: { image: 'control:dev' } },
            })
      if (args[0] === 'up') {
        if (service === 'control' && !args.includes('--no-deps'))
          containers.set('runtime', { ...item('runtime'), Id: 'indirect-replacement' })
        if (!args.includes('--no-recreate')) containers.set(service, item(service))
        if (service === fail) throw new Error('health failed')
      }
      if (args[0] === 'stop') containers.get(service).State.Running = false
    },
  }
  try {
    await callback({ infra, containers, calls, item })
  } finally {
    await rm(stateDir, { recursive: true, force: true })
  }
}

test('lifecycle preserves PostgreSQL and borrowed services, stops own services in reverse order', async () => {
  await fakeInfra(
    async ({ infra, calls }) => {
      const lifecycle = await createLifecycle(infra)
      for (const service of ['postgres', 'redis', 'runtime', 'control'])
        await lifecycle.start(service)
      await lifecycle.stop()
      await lifecycle.stop()
      assert.deepEqual(
        calls.filter(([action]) => action === 'stop').map((args) => args.at(-1)),
        ['control', 'runtime'],
      )
      assert.ok(calls.find((args) => args.at(-1) === 'redis').includes('--no-recreate'))
      assert.ok(!calls.find((args) => args.at(-1) === 'control').includes('--no-recreate'))
    },
    { running: ['redis'] },
  )
})

test('starting control does not recreate or claim an already running runtime', async () => {
  await fakeInfra(
    async ({ infra, containers, calls }) => {
      const runtime = containers.get('runtime')
      const lifecycle = await createLifecycle(infra)
      await lifecycle.start('runtime')
      await lifecycle.start('control')
      assert.equal(containers.get('runtime'), runtime)
      assert.ok(
        calls.filter(([action]) => action === 'up').every((args) => args.includes('--no-deps')),
      )
      await lifecycle.stop()
      assert.equal(runtime.State.Running, true)
      assert.deepEqual(
        calls.filter(([action]) => action === 'stop').map((args) => args.at(-1)),
        ['control'],
      )
    },
    { running: ['runtime'] },
  )
})

test('sandbox reuses unchanged images despite manifest/config IDs, but refuses source, image or config updates', async () => {
  await fakeInfra(
    async ({ infra, calls, containers }) => {
      await assertReusableSandbox(infra, { rebuildRequired: false })
      await assert.rejects(
        assertReusableSandbox(infra, { rebuildRequired: true }),
        /sandbox:stop.*sandbox:start/,
      )
      const docker = infra.docker
      infra.docker = async (args) => (args.at(-1).endsWith(':dev') ? 'new image' : 'old image')
      await assert.rejects(assertReusableSandbox(infra), /sandbox:stop.*sandbox:start/)
      infra.docker = docker
      containers.get('control').Config.Labels['com.docker.compose.config-hash'] = 'old-hash'
      await assert.rejects(assertReusableSandbox(infra), /sandbox:stop.*sandbox:start/)
      assert.equal(
        calls.filter(([action]) => ['up', 'build', 'stop', 'rm'].includes(action)).length,
        0,
      )
    },
    { running: ['runtime', 'control'] },
  )
})

test('failed startup stops the created container and releases the session lock', async () => {
  await fakeInfra(
    async ({ infra, calls }) => {
      const lifecycle = await createLifecycle(infra)
      await assert.rejects(lifecycle.start('redis'), /health failed/)
      await lifecycle.stop()
      assert.equal(calls.filter(([action]) => action === 'stop').length, 1)
      await (
        await acquireLock(infra)
      )()
    },
    { fail: 'redis' },
  )
})

test('concurrent sessions cannot claim another owner and replaced IDs are not stopped', async () => {
  await fakeInfra(async ({ infra, containers, calls, item }) => {
    const lifecycle = await createLifecycle(infra)
    await assert.rejects(createLifecycle(infra), /已有本地/)
    await lifecycle.start('redis')
    containers.set('redis', { ...item('redis'), Id: 'replacement' })
    await lifecycle.stop()
    assert.equal(calls.filter(([action]) => action === 'stop').length, 0)
  })
})

test('abort before up creates no resources and manual start can leave services running', async () => {
  await fakeInfra(async ({ infra, calls }) => {
    const signal = AbortSignal.abort()
    const cancelled = await createLifecycle(infra, { signal })
    await assert.rejects(cancelled.start('redis'), { name: 'AbortError' })
    await cancelled.stop()
    const manual = await createLifecycle(infra)
    await manual.start('redis')
    await manual.stop({ keepRunning: true })
    assert.equal(calls.filter(([action]) => action === 'stop').length, 0)
  })
})

test('external database and Redis-only legacy checks do not adopt unrelated resources', async () => {
  for (const url of [
    'postgresql://user:pass@db.example/db',
    'postgresql://user:pass@127.0.0.1:15432/db',
    'postgresql://user:pass@localhost/db?host=/tmp',
  ])
    assert.equal(usesLocalDatabase({ DATABASE_URL: url }), false)
  const names = []
  await rejectLegacy(
    {
      project: 'paa-company',
      values: {},
      inspect: async (name) => {
        names.push(name)
        return null
      },
    },
    undefined,
    ['redis'],
  )
  assert.deepEqual(names, ['paa-company-reply-redis'])
})

test('Compose has no sandbox requirements when disabled, mappings cannot cross project boundaries', async () => {
  await fakeInfra(async ({ infra }) => {
    const plain = await createInfra({ values: {}, stateDir: infra.stateDir })
    assert.ok(!plain.base.includes('deploy/company/compose.sandbox-local.yml'))
    await writeFile(
      join(infra.stateDir, 'resources.json'),
      JSON.stringify({ project: 'different' }),
    )
    await assert.rejects(createInfra({ values: {}, stateDir: infra.stateDir }), /其他项目/)
  })
})

test('Windows shutdown targets only the owned PID tree; Unix targets its isolated process group', async () => {
  const { signalOwnedChild } = await import('../../scripts/company/local-infra/processes.mjs')
  const child = { pid: 12345, exitCode: null, signalCode: null }
  const calls = []
  signalOwnedChild(child, 'SIGTERM', {
    platform: 'win32',
    launch: (...args) => {
      calls.push(args)
      return { on: () => {} }
    },
  })
  assert.deepEqual(calls[0][1], ['/PID', '12345', '/T'])
  signalOwnedChild(child, 'SIGKILL', { platform: 'linux', kill: (...args) => calls.push(args) })
  assert.deepEqual(calls[1], [-12345, 'SIGKILL'])
})
