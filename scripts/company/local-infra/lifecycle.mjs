import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { randomUUID } from 'node:crypto'

export const imageIdentityFormat =
  '{{json .Config}} {{json .RootFS.Layers}} {{.Architecture}} {{.Os}}'
export const sandboxRestartMessage =
  '本地沙盒源码、镜像或配置已变化，请先执行 npm run sandbox:stop，再执行 npm run sandbox:start；不会重建正在使用的服务。'

function assertOwned(infra, service, item) {
  if (
    item &&
    (item.Config.Labels?.['com.docker.compose.project'] !== infra.project ||
      item.Config.Labels?.['com.docker.compose.service'] !== service)
  )
    throw new Error(`容器 ${infra.name(service)} 不属于当前项目，拒绝接管。`)
}

export async function assertSandboxCurrent(infra, service, item, { signal } = {}) {
  assertOwned(infra, service, item)
  if (!item?.State.Running) return
  const hashLine = (await infra.compose(['config', '--hash', service], { signal }))
    .split('\n')
    .find((line) => line.startsWith(`${service} `))
  const hash = hashLine?.trim().split(/\s+/)[1]
  if (!hash || hash !== item.Config.Labels?.['com.docker.compose.config-hash'])
    throw new Error(sandboxRestartMessage)
  const config = JSON.parse(await infra.compose(['config', '--format', 'json'], { signal }))
  const image = config.services[service].image
  // Desktop can expose a manifest ID for a tag and a config ID for its container.
  const identity = async (reference) =>
    infra.docker(['image', 'inspect', '--format', imageIdentityFormat, reference], { signal })
  if ((await identity(image)) !== (await identity(item.Image)))
    throw new Error(sandboxRestartMessage)
}

export async function assertReusableSandbox(infra, { rebuildRequired, signal } = {}) {
  for (const service of ['runtime', 'control']) {
    const item = await infra.inspect(infra.name(service), { signal })
    assertOwned(infra, service, item)
    if (item?.State.Running && rebuildRequired) throw new Error(sandboxRestartMessage)
    await assertSandboxCurrent(infra, service, item, { signal })
  }
}

export function processAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return error.code === 'EPERM'
  }
}

export async function acquireLock(infra) {
  await mkdir(infra.stateDir, { recursive: true, mode: 0o700 })
  const file = join(infra.stateDir, 'owner.lock')
  const owner = { pid: process.pid, id: randomUUID(), project: infra.project }
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await writeFile(file, JSON.stringify(owner), { flag: 'wx', mode: 0o600 })
      return async () => {
        const current = await readFile(file, 'utf8').then(JSON.parse, () => null)
        if (current?.id === owner.id) await rm(file, { force: true })
      }
    } catch (error) {
      if (error.code !== 'EEXIST') throw error
      const current = await readFile(file, 'utf8').then(JSON.parse, () => null)
      if (!current || processAlive(current.pid))
        throw new Error('已有本地启动或迁移命令运行，请先退出该命令；不会接管或停止它的服务。')
      await rm(file, { force: true })
    }
  }
  throw new Error('无法取得本地服务管理锁，请稍后重试。')
}

export async function createLifecycle(infra, { signal } = {}) {
  const release = await acquireLock(infra)
  const owned = new Map()
  let stopped = false
  const stop = async ({ keepRunning = false } = {}) => {
    if (stopped) return
    stopped = true
    const errors = []
    try {
      if (!keepRunning)
        for (const [service, id] of [...owned].reverse()) {
          if (service === 'postgres') continue
          try {
            const current = await infra.inspect(infra.name(service))
            if (
              current?.Id === id &&
              current.Config.Labels?.['com.docker.compose.project'] === infra.project
            )
              await infra.compose(['stop', '--timeout', '20', service], { timeout: 30_000 })
          } catch (error) {
            errors.push(error)
          }
        }
    } finally {
      await release()
    }
    if (errors.length)
      throw new AggregateError(errors, '部分本地服务未能停止，请检查 Docker 状态。')
  }
  const start = async (service, seconds = 60) => {
    signal?.throwIfAborted()
    const name = infra.name(service)
    const before = await infra.inspect(name, { signal })
    assertOwned(infra, service, before)
    if (['runtime', 'control'].includes(service))
      await assertSandboxCurrent(infra, service, before, { signal })
    try {
      await infra.compose(
        [
          'up',
          '-d',
          '--no-deps',
          ...(before?.State.Running ? ['--no-recreate'] : []),
          '--no-build',
          '--wait',
          '--wait-timeout',
          String(seconds),
          service,
        ],
        { signal, timeout: (seconds + 30) * 1000 },
      )
    } finally {
      if (!before?.State.Running) {
        const after = await infra.inspect(name)
        if (after?.Config.Labels?.['com.docker.compose.project'] === infra.project)
          owned.set(service, after.Id)
      }
    }
    signal?.throwIfAborted()
  }
  return { start, stop, infra }
}
