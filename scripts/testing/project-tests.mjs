import { spawn } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, createWriteStream, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

export function summarizeNative(report, kind) {
  if (kind === 'normalized') return report
  if (kind === 'vitest') {
    const cases = report.testResults.flatMap((file) =>
      file.assertionResults.map((item) => ({
        id: `${file.name}:${item.fullName}`,
        status:
          item.status === 'passed' ? 'passed' : item.status === 'failed' ? 'failed' : 'skipped',
      })),
    )
    return { cases, complete: report.success === true }
  }
  if (kind === 'playwright') {
    const cases = []
    const walk = (suite) => {
      for (const spec of suite.specs ?? [])
        for (const test of spec.tests ?? []) {
          const results = test.results ?? []
          cases.push({
            id: `${spec.file}:${spec.line}:${spec.title}`,
            dimension: test.projectName,
            status:
              results.length === 1 &&
              results[0].status === 'passed' &&
              test.expectedStatus === 'passed'
                ? 'passed'
                : results.some((r) => ['failed', 'timedOut', 'interrupted'].includes(r.status))
                  ? 'failed'
                  : 'skipped',
          })
        }
      for (const child of suite.suites ?? []) walk(child)
    }
    for (const suite of report.suites ?? []) walk(suite)
    return { cases, complete: !report.errors?.length }
  }
  throw new Error(`Unsupported native report: ${kind}`)
}
export function outcome(exitCode, native) {
  if (exitCode !== 0) return 'failed'
  if (!native || !native.complete || native.cases.length === 0) return 'blocked'
  return native.cases.every((c) => c.status === 'passed') ? 'passed' : 'failed'
}
const escape = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  )
export function saveSummary(directory, summary) {
  mkdirSync(directory, { recursive: true })
  writeFileSync(resolve(directory, 'summary.json'), JSON.stringify(summary, null, 2))
  writeFileSync(
    resolve(directory, 'index.html'),
    `<!doctype html><meta charset="utf-8"><title>Project tests</title><style>body{font:16px system-ui;margin:2rem;max-width:1000px}td,th{padding:.6rem;text-align:left;border-bottom:1px solid #bbb}pre{white-space:pre-wrap}</style><h1>${escape(summary.status)}</h1><p>${escape(summary.runId)} · ${escape(summary.source.commit)} · ${escape(summary.platform)}</p><p>原生结果；截图仍需目视审查。未选择套件不代表通过。</p><table><tr><th>运行组</th><th>结果</th><th>执行 / 不同用例</th><th>耗时</th><th>证据</th></tr>${summary.groups.map((g) => `<tr><td>${escape(g.id)}<br>${escape(g.boundary)}</td><td>${escape(g.status)}<br>${escape(g.reason ?? '')}</td><td>${g.cases?.length ?? 0} / ${new Set(g.cases?.map((c) => c.id)).size}</td><td>${g.durationMs ?? 0} ms</td><td><a href="${escape(g.id)}/output.log">log</a> <a href="${escape(g.id)}/results.json">native JSON</a></td></tr>`).join('')}</table><pre>${escape(JSON.stringify(summary, null, 2))}</pre>`,
  )
}
const delay = (ms) => new Promise((accept) => setTimeout(accept, ms))
function groupAlive(pid) {
  try {
    process.kill(-pid, 0)
    return true
  } catch (error) {
    if (error.code === 'ESRCH') return false
    throw error
  }
}
export async function reapGroup(pid, graceMs = 15000) {
  // Never infer group death from the leader's close event or its stdio pipes.
  if (process.platform === 'win32')
    throw new Error('Owned process-group reclamation requires POSIX; Windows is not supported yet')
  const signal = (name) => {
    try {
      process.kill(-pid, name)
    } catch (error) {
      if (error.code !== 'ESRCH') throw error
    }
  }
  if (!groupAlive(pid)) return
  signal('SIGTERM')
  const deadline = Date.now() + graceMs
  while (groupAlive(pid) && Date.now() < deadline) await delay(50)
  if (!groupAlive(pid)) return
  signal('SIGKILL')
  const forcedDeadline = Date.now() + 5000
  while (groupAlive(pid) && Date.now() < forcedDeadline) await delay(50)
  if (groupAlive(pid)) throw new Error(`Owned process group ${pid} still exists`)
}
function checkedRedis(env, runId) {
  return JSON.parse(
    execFileSync('python3', ['scripts/testing/redis-environment.py', runId], {
      env,
      encoding: 'utf8',
    }),
  )
}
async function wrapper(args) {
  if (process.platform === 'win32') throw new Error('Owned wrappers currently require POSIX')
  const runId = randomUUID()
  const env = {
    ...process.env,
    PYTHON_DOTENV_DISABLED: '1',
    PROJECT_TEST_OWNED_GROUP: '1',
    ...checkedRedis(process.env, runId),
  }
  const child = spawn(args[0], args.slice(1), { env, detached: true, stdio: 'inherit' })
  let reaping
  let abortWait
  const cancel = () => {
    if (!reaping) {
      reaping = reapGroup(child.pid)
      reaping.catch((error) => abortWait?.(error))
    }
  }
  process.on('SIGINT', cancel)
  process.on('SIGTERM', cancel)
  let exit
  try {
    exit = await new Promise((accept, reject) => {
      abortWait = reject
      child.once('error', reject)
      child.once('close', accept)
    })
  } finally {
    await (reaping ?? (child.pid ? reapGroup(child.pid) : Promise.resolve()))
    const manifest = resolve(env.PROJECT_TEST_OUTPUT, 'environment.json')
    if (existsSync(manifest) && !JSON.parse(readFileSync(manifest, 'utf8')).cleaned)
      execFileSync(
        args[0],
        ['scripts/company/web-acceptance/environment.py', 'cleanup', '--metadata', manifest],
        { env, stdio: 'inherit', timeout: 30000 },
      )
  }
  process.exitCode = exit === 0 && !reaping ? 0 : 1
}
async function main() {
  const root = resolve(import.meta.dirname, '../..')
  process.chdir(root)
  if (process.argv[2] === '--owned-wrapper') return wrapper(process.argv.slice(3))
  const config = JSON.parse(readFileSync('tests/suites.json', 'utf8'))
  const args = process.argv.slice(2)
  if (args.length === 2 && args[0] === '--report') {
    const directory = resolve(args[1])
    saveSummary(directory, JSON.parse(readFileSync(resolve(directory, 'summary.json'), 'utf8')))
    console.log(resolve(directory, 'index.html'))
    return
  }
  if (args.length === 1 && args[0] === '--list') {
    console.log(JSON.stringify(config, null, 2))
    return
  }
  if (args.length !== 2 || args[0] !== '--suite')
    throw new Error('Use --list, --suite NAME[,NAME], or --report RUN_DIRECTORY')
  if (process.platform === 'win32')
    throw new Error('Owned project test execution currently requires POSIX')
  const selected = args[1].split(',')
  if (selected.some((name) => !config.suites[name])) throw new Error('Unknown suite')
  const ids = [...new Set(selected.flatMap((name) => config.suites[name]))]
  const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${randomUUID().slice(0, 8)}`
  const directory = resolve('artifacts/project-tests', runId)
  const git = (...args) => execFileSync('git', args, { encoding: 'utf8' }).trim()
  const sourceFiles = git('ls-files', '--cached', '--others', '--exclude-standard', '-z')
    .split('\0')
    .filter(Boolean)
  const sourceHash = createHash('sha256')
  for (const file of [...new Set(sourceFiles)].sort()) {
    try {
      sourceHash.update(file).update('\0').update(readFileSync(file)).update('\0')
    } catch (error) {
      if (error.code !== 'ENOENT') throw error
      sourceHash.update(file + ':deleted')
    }
  }
  const summary = {
    runId,
    platform: `${process.platform}/${process.arch}`,
    source: {
      commit: git('rev-parse', 'HEAD'),
      workspaceHash: sourceHash.digest('hex'),
      status: git('status', '--short'),
    },
    selected,
    status: 'running',
    groups: ids.map((id) => ({ ...config.groups[id], id, status: 'not-run' })),
  }
  let cancelled = false
  let child
  let reaping
  let abortWait
  const cancel = () => {
    cancelled = true
    if (child?.pid && !reaping) {
      reaping = reapGroup(child.pid)
      reaping.catch((error) => abortWait?.(error))
    }
  }
  process.on('SIGINT', cancel)
  process.on('SIGTERM', cancel)
  saveSummary(directory, summary)
  for (const group of summary.groups) {
    if (cancelled) {
      group.reason = 'Cancelled before start'
      continue
    }
    const output = resolve(directory, group.id)
    mkdirSync(output, { recursive: true })
    const env = Object.fromEntries(
      Object.entries(process.env).filter(
        ([key]) =>
          !/(API_KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL|DATABASE_TEST_URL|PAA_AGENT|PAA_ASR)/i.test(
            key,
          ),
      ),
    )
    if (
      ['web-ui', 'web-flow', 'server', 'server-critical'].includes(group.id) &&
      process.env.DATABASE_TEST_URL
    )
      env.DATABASE_TEST_URL = process.env.DATABASE_TEST_URL
    Object.assign(env, {
      PYTHON_DOTENV_DISABLED: '1',
      PROJECT_TEST_RUN_ID: runId,
      PROJECT_TEST_OUTPUT: output,
      ...group.env,
      PROJECT_TEST_OWNED_GROUP: '1',
    })
    Object.assign(env, checkedRedis(env, runId))
    const command = group.command.map((value) =>
      value
        .replaceAll('{output}', output)
        .replace(
          '.venv-server/bin/python',
          process.platform === 'win32'
            ? '.venv-server/Scripts/python.exe'
            : '.venv-server/bin/python',
        ),
    )
    group.command = command
    const started = Date.now()
    const log = createWriteStream(resolve(output, 'output.log'))
    let timedOut = false
    try {
      const exit = await new Promise((accept, reject) => {
        abortWait = reject
        child = spawn(command[0], command.slice(1), {
          cwd: root,
          env,
          detached: process.platform !== 'win32',
          stdio: ['ignore', 'pipe', 'pipe'],
        })
        child.stdout.pipe(log, { end: false })
        child.stderr.pipe(log, { end: false })
        const timer = setTimeout(() => {
          timedOut = true
          cancel()
        }, group.timeoutMs)
        child.once('error', (error) => {
          clearTimeout(timer)
          reject(error)
        })
        child.once('close', (code, signal) => {
          clearTimeout(timer)
          accept({ code, signal })
        })
      })
      group.exit = exit
      if (group.junit)
        execFileSync('python3', [
          'scripts/testing/read-junit.py',
          resolve(output, 'results.xml'),
          resolve(output, 'results.json'),
        ])
      let native
      if (group.reporter)
        native = summarizeNative(
          JSON.parse(readFileSync(resolve(output, 'results.json'), 'utf8')),
          group.reporter,
        )
      group.cases = native?.cases ?? []
      group.status = outcome(exit.code, native)
      if (!native) group.reason = 'Command-level evidence only; native case report unavailable'
      if (timedOut || cancelled) {
        group.status = 'failed'
        group.reason = timedOut ? 'Timeout' : 'Cancelled'
      }
    } catch (error) {
      group.status =
        timedOut || cancelled || (group.exit && group.exit.code !== 0) ? 'failed' : 'blocked'
      group.reason = timedOut
        ? 'Timeout; ' + error.message
        : cancelled
          ? 'Cancelled; ' + error.message
          : error.message
    } finally {
      let reclaimed = false
      try {
        await (reaping ?? (child?.pid ? reapGroup(child.pid) : Promise.resolve()))
        reclaimed = true
      } catch (error) {
        group.status = 'failed'
        group.cleanupError = `Process reclamation failed; environment retained: ${error.message}`
        cancelled = true
      }
      reaping = undefined
      const manifest = resolve(output, 'environment.json')
      if (reclaimed && existsSync(manifest)) {
        try {
          const environment = JSON.parse(readFileSync(manifest, 'utf8'))
          if (!environment.cleaned)
            execFileSync(
              resolve(
                '.venv-server',
                process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
              ),
              ['scripts/company/web-acceptance/environment.py', 'cleanup', '--metadata', manifest],
              { env, stdio: 'pipe', timeout: 30000 },
            )
        } catch (error) {
          group.status = 'failed'
          group.cleanupError = error.message
        }
      }
      log.end()
      child = undefined
      group.durationMs = Date.now() - started
      saveSummary(directory, summary)
    }
    console.log(`${group.id}: ${group.status}`)
  }
  summary.status = summary.groups.some((g) => g.status === 'failed')
    ? 'failed'
    : summary.groups.every((g) => g.status === 'passed')
      ? 'passed'
      : 'incomplete'
  saveSummary(directory, summary)
  console.log(resolve(directory, 'index.html'))
  process.exitCode = summary.status === 'passed' ? 0 : 1
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch((error) => {
    console.error(error)
    process.exitCode = 1
  })
