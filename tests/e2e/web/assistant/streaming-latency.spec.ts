import { test, expect } from '../fixtures/test'
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { once } from 'node:events'
import { writeFileSync } from 'node:fs'

test.use({ reducedMotion: 'no-preference' })

declare global {
  interface Window {
    latencySources: (EventTarget & { closed: boolean; url: string; onerror?: () => void })[]
  }
}

test('S55 delta stream: first paint, duplicate/gap recovery, refresh and final handoff', async ({
  page,
  state,
  login,
  capture,
}, info) => {
  await page.addInitScript(() => {
    window.latencySources = []
    class ControlledSource extends EventTarget {
      closed = false
      constructor(public url: string) {
        super()
        window.latencySources.push(this)
      }
      close() {
        this.closed = true
      }
    }
    window.EventSource = ControlledSource as unknown as typeof EventSource
  })
  await login('employee')
  let job = {
    id: 'latency-job',
    targetId: 'latency-message',
    kind: 'message',
    phase: 'assistant',
    state: 'running',
    attempt: 1,
    fence: 2,
    error: '',
    updatedAt: new Date().toISOString(),
    nodes: [],
  }
  let message = {
    id: job.targetId,
    ownerId: state.users.employee.id,
    conversationId: 'latency-conversation',
    text: '测试增量呈现',
    reply: '',
    replyTo: null,
    transcript: '',
    transcriptRevision: 0,
    createdAt: job.updatedAt,
    attachments: [],
    drafts: [],
    suggestions: [],
    job,
  }
  const writes: string[] = []
  let recoveryReads = 0
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    if (request.method() === 'POST') writes.push(path)
    let data: unknown
    if (path === `/conversations/${message.conversationId}`)
      data = {
        id: message.conversationId,
        title: '增量恢复测试',
        revision: 1,
        personaId: 'professional',
      }
    else if (path === `/conversations/${message.conversationId}/active-job`)
      data = { job: job.state === 'running' ? job : null }
    else if (path === `/conversations/${message.conversationId}/context-usage`)
      data = { contextUsage: null }
    else if (path === `/conversations/${message.conversationId}/interactions`) data = { items: [] }
    else if (
      path === '/messages' &&
      url.searchParams.get('conversationId') === message.conversationId
    )
      data = { items: [message], nextCursor: null }
    else if (path === `/messages/${message.id}`) data = message
    else if (path === `/jobs/${job.id}`) data = job
    else if (path === `/jobs/${job.id}/feedback`) {
      recoveryReads++
      data = feedback()
    } else if (path === '/business-actions') data = { items: [] }
    else return route.continue()
    await route.fulfill({ json: data })
  })
  const feedback = () => ({ ...job, jobId: job.id, seq: 1, stage: 'generating', text: '' })
  const packet = (seq: number, extra: Record<string, unknown> = {}) => ({
    jobId: job.id,
    attempt: 1,
    fence: 2,
    generation: 1,
    seq,
    callId: 'controlled-call',
    state: 'streaming',
    ...extra,
  })
  async function emit(type: string, value: unknown) {
    await page.evaluate(
      ({ type, value }) => {
        for (const source of window.latencySources.filter((source) => !source.closed))
          source.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(value) }))
      },
      { type, value },
    )
  }
  async function connected() {
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            window.latencySources.filter(
              (source) => !source.closed && source.url.endsWith('?version=2'),
            ).length,
        ),
      )
      .toBe(1)
    await emit('snapshot', feedback())
  }
  await page.goto(state.origin + '/assistant/' + message.conversationId)
  await connected()
  // Leaving before any answer must not cancel or resend the admitted task.
  await page.getByRole('link', { name: '我的工作', exact: true }).click()
  await expect
    .poll(() => page.evaluate(() => window.latencySources.filter((s) => !s.closed).length))
    .toBe(0)
  await page.goto(state.origin + '/assistant/' + message.conversationId)
  await connected()
  const input = await page.getByRole('textbox', { name: '工作消息' }).elementHandle()
  const stop = await page.getByRole('button', { name: '中断', exact: true }).elementHandle()
  const firstPaintMs = await page.evaluate(
    async (value) => {
      const start = performance.now()
      for (const source of window.latencySources.filter((source) => !source.closed))
        source.dispatchEvent(new MessageEvent('reply_sync', { data: JSON.stringify(value) }))
      while (performance.now() - start < 2000) {
        await new Promise(requestAnimationFrame)
        if (document.querySelector('[data-reply-state="streaming"]')?.textContent?.includes('首')) {
          await new Promise(requestAnimationFrame)
          return performance.now() - start
        }
      }
      return 2000
    },
    packet(1, { text: '首段内容。' }),
  )
  expect(firstPaintMs).toBeLessThan(1000)
  await emit('reply_delta', packet(2, { delta: '第二段。' }))
  await emit('reply_delta', packet(2, { delta: '不能重复。' }))
  await emit('reply_delta', packet(4, { delta: '不能越过缺口。' }))
  const preview = page.locator('[data-reply-state="streaming"]')
  await expect(preview).toHaveText('首段内容。第二段。')
  await emit('reply_sync', packet(4, { text: '首段内容。第二段。恢复缺口。' }))
  await expect(preview).toHaveText('首段内容。第二段。恢复缺口。')
  expect(await input!.evaluate((node) => node.isConnected)).toBe(true)
  expect(await stop!.evaluate((node) => node.isConnected)).toBe(true)
  for (let n = 0; n < 2; n++) {
    await page.reload()
    await connected()
    await emit('reply_sync', packet(4, { text: '首段内容。第二段。恢复缺口。' }))
    await expect(preview).toHaveText('首段内容。第二段。恢复缺口。')
  }
  await emit('reply_delta', packet(5, { delta: '刷新后继续。' }))
  await expect(preview).toHaveText('首段内容。第二段。恢复缺口。刷新后继续。')
  const connections = await page.evaluate(() => window.latencySources.length)
  await page.context().setOffline(true)
  await page.evaluate(() => {
    for (const source of window.latencySources.filter((source) => !source.closed))
      source.onerror?.()
  })
  await expect
    .poll(() => page.evaluate(() => window.latencySources.filter((s) => !s.closed).length))
    .toBe(0)
  expect(await page.evaluate(() => window.latencySources.length)).toBe(connections)
  await page.context().setOffline(false)
  await connected()
  expect(recoveryReads).toBe(1)
  expect(await page.evaluate(() => window.latencySources.length)).toBe(connections + 1)
  await emit('reply_sync', packet(5, { text: '首段内容。第二段。恢复缺口。刷新后继续。' }))
  await expect(preview).toHaveText('首段内容。第二段。恢复缺口。刷新后继续。')
  await emit('reply_withdrawn', packet(6, { state: 'withdrawn' }))
  await expect(preview).toHaveCount(0)
  await emit('reply_sync', packet(1, { generation: 2, text: '新一版正文。' }))
  await emit('reply_delta', packet(99, { generation: 1, delta: '旧正文不能返回。' }))
  await expect(preview).toHaveText('新一版正文。')
  await capture('v2-streaming')
  const finalBody = '完整结果立即展示，不等待逐字动画。'.repeat(100)
  const final = '# 最终正文\n\n' + finalBody
  job = { ...job, state: 'succeeded' }
  message = { ...message, reply: final, job }
  const terminal = await page.evaluate(
    async ({ value, body }) => {
      const start = performance.now()
      for (const source of window.latencySources.filter((source) => !source.closed))
        source.dispatchEvent(new MessageEvent('snapshot', { data: JSON.stringify(value) }))
      while (performance.now() - start < 3000) {
        await new Promise(requestAnimationFrame)
        const heading = [...document.querySelectorAll('h4')].find(
          (node) => node.textContent === '最终正文',
        )
        if (heading) {
          const completeOnFirstFrame = heading.parentElement?.textContent?.includes(body)
          await new Promise(requestAnimationFrame)
          return { paintMs: performance.now() - start, completeOnFirstFrame }
        }
      }
      return { paintMs: 3000, completeOnFirstFrame: false }
    },
    { value: { ...feedback(), seq: 2 }, body: finalBody },
  )
  expect(terminal.completeOnFirstFrame).toBe(true)
  expect(terminal.paintMs).toBeLessThan(1000)
  await expect(page.getByRole('heading', { name: '最终正文', exact: true })).toHaveCount(1)
  await expect(preview).toHaveCount(0)
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
  expect(writes).toEqual([])
  const metricsPath = info.outputPath('browser-latency.json')
  writeFileSync(
    metricsPath,
    JSON.stringify({
      eventDispatchToPaintMs: firstPaintMs,
      terminalToPaintMs: terminal.paintMs,
      completeOnFirstFrame: terminal.completeOnFirstFrame,
      clock: 'browser performance.now',
      scope: 'controlled client presentation; excludes API and Redis',
    }),
  )
  await info.attach('browser-latency', { path: metricsPath, contentType: 'application/json' })
  await capture('v2-final')
})

test('S55 real publisher through Redis and HTTP to browser paint', async ({
  page,
  state,
  login,
  capture,
}, info) => {
  test.skip(!process.env.SPEC055_REAL_STREAM, 'Requires the owned Spec055 API and Redis')
  await login('employee')
  const publisher = spawn(
    '.venv-server/bin/python',
    ['tests/e2e/web/assistant/controlled_reply.py', process.env.SPEC054_ENVIRONMENT!],
    { stdio: ['pipe', 'pipe', 'pipe'] },
  )
  const lines = createInterface({ input: publisher.stdout! })[Symbol.asyncIterator]()
  let errors = ''
  publisher.stderr!.on('data', (data: Buffer) => {
    errors += data.toString()
  })
  async function next() {
    const line = await lines.next()
    expect(line.done, errors).not.toBe(true)
    return JSON.parse(line.value!)
  }
  try {
    const ready = await next()
    const connection = page.waitForResponse(
      (response) => response.url().includes('/events?version=2') && response.status() === 200,
    )
    await page.goto(state.origin + '/assistant/' + ready.conversationId)
    await connection
    const paint = page.evaluate(async () => {
      const deadline = performance.now() + 5000
      while (performance.now() < deadline) {
        await new Promise(requestAnimationFrame)
        if (
          document.querySelector('[data-reply-state="streaming"]')?.textContent?.includes('真实')
        ) {
          await new Promise(requestAnimationFrame)
          return performance.timeOrigin + performance.now()
        }
      }
      return null
    })
    publisher.stdin!.write('publish\n')
    const emitted = await next()
    const painted = await paint
    expect(painted).not.toBeNull()
    const transportToPaintMs = painted! - emitted.candidateEpochMs
    expect(transportToPaintMs).toBeGreaterThanOrEqual(0)
    expect(transportToPaintMs).toBeLessThan(1000)
    await expect(page.locator('[data-reply-state="streaming"]')).toHaveText('真实通道首段正文。')
    await page.reload()
    await expect(page.locator('[data-reply-state="streaming"]')).toHaveText('真实通道首段正文。')
    await page.getByRole('button', { name: '中断', exact: true }).click()
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
    await expect(page.getByText('真实通道首段正文。', { exact: true })).toHaveCount(1)
    await page.reload()
    await expect(page.getByText('真实通道首段正文。', { exact: true })).toHaveCount(1)
    const metricsPath = info.outputPath('real-transport-latency.json')
    writeFileSync(
      metricsPath,
      JSON.stringify({
        transportToPaintMs,
        candidateEpochMs: emitted.candidateEpochMs,
        paintedEpochMs: painted,
        clock:
          'same-host epoch milliseconds; Python time.time_ns and browser performance.timeOrigin + performance.now',
      }),
    )
    await info.attach('real-transport-latency', {
      path: metricsPath,
      contentType: 'application/json',
    })
    await capture('real-stream-cancelled-restored')
  } finally {
    if (publisher.exitCode === null) {
      const exited = once(publisher, 'exit')
      publisher.stdin!.end('close\n')
      await exited
    }
    expect(publisher.exitCode, errors).toBe(0)
  }
})
