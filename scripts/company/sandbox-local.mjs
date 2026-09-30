import { spawn } from 'node:child_process'
import { createHash, randomBytes } from 'node:crypto'
import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseEnv } from 'node:util'
import { pathToFileURL } from 'node:url'

const root = resolve(import.meta.dirname, '../..')
const envFile = join(root, 'apps/server/.env.web')
const stateDir = join(root, 'data/company/sandbox-local')
const project = `noria-sandbox-${createHash('sha256').update(root).digest('hex').slice(0, 10)}`
const composeFile = 'deploy/company/compose.sandbox-local.yml'

export function localConfig(values) {
  const port = Number(values.PAA_SANDBOX_LOCAL_PORT || 8011)
  if (!Number.isInteger(port) || port < 1024 || port > 65535)
    throw new Error('本地沙盒端口必须为 1024～65535。')
  const url = `http://127.0.0.1:${port}`
  if (values.PAA_SANDBOX_URL && values.PAA_SANDBOX_URL !== url)
    throw new Error('已配置其他沙盒地址；请先明确切换到本地沙盒，原配置未被覆盖。')
  return { url, port, token: values.PAA_SANDBOX_TOKEN || randomBytes(32).toString('hex') }
}

export function patchLocalEnv(source, config) {
  const replacements = {
    PAA_SANDBOX_LOCAL: 'true',
    PAA_SANDBOX_URL: config.url,
    PAA_SANDBOX_TOKEN: config.token,
  }
  const remaining = new Set(Object.keys(replacements))
  const lines = source.split(/\r?\n/).flatMap((line) => {
    const key = line.match(/^\s*(?:export\s+)?([A-Z_]+)\s*=/)?.[1]
    if (!Object.hasOwn(replacements, key)) return [line]
    if (!remaining.delete(key)) return []
    return [`${key}=${JSON.stringify(replacements[key])}`]
  })
  for (const key of remaining) lines.push(`${key}=${JSON.stringify(replacements[key])}`)
  return lines.join('\n').trimEnd() + '\n'
}

async function settings() {
  const source = await readFile(envFile, 'utf8')
  return { source, values: { ...parseEnv(source), ...process.env } }
}

function command(args, env, { capture = false, signal } = {}) {
  return new Promise((accept, reject) => {
    const child = spawn('docker', args, {
      cwd: root,
      env,
      signal,
      stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
    })
    let output = ''
    if (capture) {
      child.stdout.on('data', (chunk) => {
        output += chunk
      })
      child.stderr.resume()
    }
    child.on('error', reject)
    child.on('close', (code) =>
      code === 0
        ? accept(output.trim())
        : reject(
            new Error(`Docker 命令失败（${code ?? '已中断'}）：${args.slice(0, 2).join(' ')}`),
          ),
    )
  })
}

function commands(config) {
  const env = {
    ...process.env,
    LOCAL_SANDBOX_PROJECT: project,
    PAA_SANDBOX_TOKEN: config.token,
    PAA_SANDBOX_LOCAL_PORT: String(config.port),
  }
  const base = ['compose', '--progress', 'plain', '-p', project, '-f', composeFile]
  return {
    env,
    base,
    docker: (args, options) => command(args, env, options),
    compose: (args, options) => command([...base, ...args], env, options),
  }
}

async function fingerprint() {
  const hash = createHash('sha256')
  async function visit(path) {
    const entries = await readdir(join(root, path), { withFileTypes: true })
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      if (entry.name === '__pycache__' || entry.name.startsWith('.')) continue
      const file = join(path, entry.name)
      if (entry.isDirectory()) await visit(file)
      else if (entry.isFile()) hash.update(file).update(await readFile(join(root, file)))
    }
  }
  await visit('apps/sandbox')
  for (const file of [
    composeFile,
    'deploy/company/Dockerfile.sandbox',
    'deploy/company/Dockerfile.sandbox-local',
  ])
    hash.update(await readFile(join(root, file)))
  return hash.digest('hex')
}

async function loadRunner({ env, base }, signal) {
  console.log('正在将执行镜像载入本地沙盒（首次较慢，后续复用）…')
  await new Promise((accept, reject) => {
    const save = spawn('docker', ['image', 'save', `${project}-runner:dev`], {
      env,
      signal,
      stdio: ['ignore', 'pipe', 'inherit'],
    })
    const load = spawn('docker', [...base, 'exec', '-T', 'runtime', 'docker', 'load'], {
      cwd: root,
      env,
      signal,
      stdio: ['pipe', 'inherit', 'inherit'],
    })
    let completed = 0
    const fail = (error) => {
      save.kill()
      load.kill()
      reject(error)
    }
    for (const child of [save, load]) {
      child.on('error', fail)
      child.on('exit', (code) => {
        if (code !== 0) fail(new Error('执行镜像载入失败。'))
        else if (++completed === 2) accept()
      })
    }
    load.stdin.on('error', fail)
    save.stdout.pipe(load.stdin)
  })
}

export async function startLocalSandbox({ signal } = {}) {
  const { values } = await settings()
  if (values.PAA_SANDBOX_LOCAL !== 'true') return null
  const config = localConfig(values)
  if (!values.PAA_SANDBOX_TOKEN || config.token.length < 32)
    throw new Error('请先执行 npm run sandbox:setup 初始化本地沙盒。')
  const cli = commands(config)
  const { docker, compose } = cli
  if ((await docker(['info', '--format', '{{.OSType}}'], { capture: true, signal })) !== 'linux')
    throw new Error('本地沙盒需要已启动的 Docker Linux 容器环境。')
  const before = new Set(
    (await compose(['ps', '--status', 'running', '--services'], { capture: true, signal })).split(
      '\n',
    ),
  )
  const owned = ['control', 'runtime'].filter((name) => !before.has(name))
  const stop = async () => {
    if (owned.length) await compose(['stop', ...owned])
  }
  try {
    const digest = await fingerprint()
    const cached = await readFile(join(stateDir, 'build.sha256'), 'utf8').catch(() => '')
    let images = false
    try {
      await docker(
        [
          'image',
          'inspect',
          ...['runtime', 'control', 'runner'].map((name) => `${project}-${name}:dev`),
        ],
        { capture: true, signal },
      )
      images = true
    } catch {
      /* Missing images are rebuilt below. */
    }
    if (cached !== digest || !images) {
      console.log('正在准备本地沙盒镜像；首次需要下载运行环境…')
      await compose(['build', 'runtime', 'control', 'runner-image'], { signal })
      await mkdir(stateDir, { recursive: true, mode: 0o700 })
      await writeFile(join(stateDir, 'build.sha256'), digest)
    }
    signal?.throwIfAborted()
    await compose(['up', '-d', '--wait', '--wait-timeout', '90', 'runtime'], { signal })
    const image = `${project}-runner:dev`
    // Docker Desktop may report a manifest index ID while DinD reports a config ID.
    // Compare the actual image configuration and filesystem layers across engines.
    const identity = '{{json .Config}} {{json .RootFS.Layers}} {{.Architecture}} {{.Os}}'
    const outer = await docker(['image', 'inspect', '--format', identity, image], {
      capture: true,
      signal,
    })
    const inner = await compose(
      ['exec', '-T', 'runtime', 'docker', 'image', 'inspect', '--format', identity, image],
      { capture: true, signal },
    ).catch(() => '')
    if (inner !== outer) await loadRunner(cli, signal)
    await compose(['up', '-d', '--wait', '--wait-timeout', '90', 'control'], { signal })
    const response = await fetch(`${config.url}/health`, {
      headers: { Authorization: `Bearer ${config.token}` },
      signal: AbortSignal.any([AbortSignal.timeout(10000), ...(signal ? [signal] : [])]),
    })
    if (!response.ok || !(await response.json()).ready) throw new Error('本地沙盒健康检查未通过。')
    console.log(`本地沙盒已就绪：${config.url}（gVisor，1 个并发任务）`)
    return { stop }
  } catch (error) {
    await stop().catch(() => {})
    throw error
  }
}

async function main(action) {
  const { source, values } = await settings()
  const config = localConfig(values)
  if (action === 'setup') {
    const temporary = `${envFile}.tmp-${process.pid}`
    await writeFile(temporary, patchLocalEnv(source, config), { mode: 0o600 })
    await rename(temporary, envFile)
  }
  if (action === 'start' || action === 'setup') {
    const controller = new AbortController()
    process.once('SIGINT', () => controller.abort())
    process.once('SIGTERM', () => controller.abort())
    const local = await startLocalSandbox({ signal: controller.signal })
    if (!local) throw new Error('请先执行 npm run sandbox:setup。')
    if (action === 'setup') {
      await local.stop()
      console.log('初始化完成。之后使用 npm run dev:web 即可一起启动。')
    }
  } else if (action === 'stop') await commands(config).compose(['stop', 'control', 'runtime'])
  else if (action === 'status') await commands(config).compose(['ps', '-a'])
  else throw new Error('Usage: sandbox-local.mjs setup | start | stop | status')
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href)
  main(process.argv[2]).catch((error) => {
    console.error(error.message)
    process.exitCode = 1
  })
