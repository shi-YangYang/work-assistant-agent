import type { Job, JobFeedback, TaskNode } from '@paa/api-contracts'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi } from 'vitest'
import { acceptFeedback, visibleFeedback } from '../../apps/web/src/api/job-feedback'
import { JobNotice } from '../../apps/web/src/features/jobs/components/JobNotice'
import { nodeStatus } from '../../apps/web/src/features/jobs/components/TaskNode'
import { progressView, nodeName } from '../../apps/web/src/features/jobs/utils/progress'
import { TaskProgress } from '../../apps/web/src/features/jobs/components/TaskProgress'

const node = (patch: Partial<TaskNode> = {}): TaskNode => ({
  id: 'node',
  parentId: null,
  kind: 'model',
  label: '思考中',
  state: 'running',
  attempts: 1,
  maxAttempts: 4,
  retries: 0,
  totalRetries: 0,
  round: 0,
  nextRetryAt: null,
  errorCode: '',
  error: '',
  canRetry: false,
  ...patch,
})
const job = (patch: Partial<Job> = {}): Job => ({
  id: 'job',
  targetId: 'message',
  kind: 'message',
  state: 'running',
  phase: 'assistant',
  error: '',
  updatedAt: '2026-01-01',
  attempt: 0,
  fence: 1,
  nodes: [node()],
  ...patch,
})

it('counts only retries and shows retry wait from the persisted timestamp', () => {
  expect(nodeStatus(node())).not.toContain('重试')
  expect(nodeStatus(node({ attempts: 2, retries: 1 }))).toBe('正在第 1/3 次重试')
  expect(
    nodeStatus(node({ state: 'retry_wait', nextRetryAt: new Date(3000).toISOString() }), 1000),
  ).toBe('模型暂未响应，2 秒后重试 · 1/3')
})

it('renders compact accessible progress, completion totals, and in-place manual recovery', () => {
  const render = (value: Job) =>
    renderToStaticMarkup(
      createElement(TaskProgress, {
        job: value,
        busy: false,
        onRetry: vi.fn(),
      }),
    )
  const running = render(job())
  expect(running).not.toContain('<summary>')
  expect(running).toContain('处理请求')
  expect(running).not.toContain('aria-live')
  const complete = render(
    job({
      state: 'succeeded',
      nodes: [
        node({ state: 'succeeded', attempts: 3, retries: 2, totalRetries: 2 }),
        node({ id: 'abandoned', state: 'failed', attempts: 0, round: 1 }),
      ],
    }),
  )
  expect(complete).toContain('已完成 · 自动重试 2 次')
  expect(complete).toContain('已失败')
  expect(complete).not.toContain('等待执行')
  expect(complete).not.toContain('<button')
  const failed = render(
    job({
      state: 'awaiting_retry',
      nodes: [
        node({ state: 'failed', attempts: 4, retries: 3, canRetry: true, error: '已停止自动重试' }),
      ],
    }),
  )
  expect(failed).toContain('已停止自动重试')
  expect(failed).toContain('>重试</button>')
  expect(failed.match(/<button /g)).toHaveLength(1)
  expect(failed).not.toContain('<details')
  expect(failed).not.toContain('使用当前配置')
})

it.each(['failed', 'awaiting_retry'] as const)(
  'offers one direct retry for %s before nodes exist',
  (state) => {
    const html = renderToStaticMarkup(
      createElement(JobNotice, {
        job: job({ state, nodes: [], error: '模型暂未响应' }),
        refresh: vi.fn(),
        showNodes: true,
      }),
    )
    expect(html).toContain('模型暂未响应')
    expect(html.match(/<button /g)).toHaveLength(1)
    expect(html).toContain('>重试</button>')
    expect(html).not.toMatch(/使用当前配置|确认重试|dialog/)
  },
)

it('distinguishes partial task completion from completed processing steps', () => {
  const html = renderToStaticMarkup(
    createElement(TaskProgress, {
      job: job({
        state: 'awaiting_input',
        incompleteTask: true,
        nodes: [node({ state: 'succeeded' })],
      }),
      busy: false,
      onRetry: vi.fn(),
    }),
  )
  expect(html).toContain('仍有事项未完成')
  expect(html).not.toContain('项操作')
})

it('requires explicit assistant opt-in and preserves other JobNotice presentation', () => {
  const ordinary = renderToStaticMarkup(createElement(JobNotice, { job: job(), refresh: vi.fn() }))
  expect(ordinary).not.toContain('处理步骤')
  const assistant = renderToStaticMarkup(
    createElement(JobNotice, { job: job(), refresh: vi.fn(), showNodes: true }),
  )
  expect(assistant).toContain('处理请求')
  const legacy = renderToStaticMarkup(
    createElement(JobNotice, {
      job: job({ stage: 'transcribing' }),
      refresh: vi.fn(),
      showNodes: true,
    }),
  )
  expect(legacy).toContain('正在识别语音')
})

it('restores node snapshots without accepting previous attempts, leases or accounts', () => {
  const current: JobFeedback = {
    jobId: 'job',
    attempt: 1,
    fence: 3,
    seq: 5,
    state: 'running',
    stage: 'generating',
    text: '',
    error: '',
    updatedAt: '2026-01-01',
    nodes: [node()],
  }
  const incoming = { ...current, nodes: [node({ state: 'retry_wait' })] }
  expect(acceptFeedback(current, incoming, 'job')).toBe(incoming)
  expect(acceptFeedback(current, { ...incoming, attempt: 0, seq: 9 }, 'job')).toBe(current)
  expect(acceptFeedback(current, { ...incoming, fence: 2, seq: 9 }, 'job')).toBe(current)
  expect(acceptFeedback(current, incoming, 'another-account-job')).toBe(current)
  expect(visibleFeedback(job({ attempt: 2 }), incoming)).toBeNull()
})

it('shows compaction within the existing node progress and accepts newer context-only feedback', () => {
  expect(
    nodeStatus(
      node({ kind: 'compaction', state: 'retry_wait', nextRetryAt: new Date(3000).toISOString() }),
      1000,
    ),
  ).toBe('压缩重试中 · 1/3 · 2 秒后继续')
  expect(nodeStatus(node({ kind: 'compaction', attempts: 2, retries: 1 }))).toBe('压缩重试中 · 1/3')
  const current: JobFeedback = {
    jobId: 'job',
    attempt: 1,
    fence: 1,
    seq: 5,
    state: 'running',
    stage: 'compacting',
    text: '',
    error: '',
    updatedAt: '2026-01-01',
  }
  const incoming: JobFeedback = {
    ...current,
    contextUsage: {
      jobId: 'job',
      attempt: 1,
      fence: 1,
      seq: 1,
      model: 'model',
      usedTokens: 900000,
      contextWindow: 1000000,
      inputLimit: 1000000,
      outputReserve: 4096,
      capacitySource: 'override',
      thresholdRatio: 0.9,
      estimated: true,
      state: 'compacting',
      updatedAt: '2026-01-01',
    },
  }
  expect(acceptFeedback(current, incoming, 'job')).toBe(incoming)
  const html = renderToStaticMarkup(
    createElement(TaskProgress, {
      job: job({
        nodes: [node({ kind: 'compaction', state: 'succeeded', label: '上下文已压缩' })],
      }),
      busy: false,
      onRetry: vi.fn(),
    }),
  )
  expect(html).toContain('上下文已压缩')
})

it('only marks actual execution for shine and clears unfinished nodes on interruption', () => {
  const render = (value: Job) =>
    renderToStaticMarkup(createElement(TaskProgress, { job: value, busy: false, onRetry: vi.fn() }))
  expect(render(job())).toContain('data-running="true"')
  for (const value of [
    job({ state: 'queued' }),
    job({ nodes: [node({ state: 'retry_wait' })] }),
    job({ state: 'awaiting_input' }),
    job({ state: 'succeeded' }),
  ]) {
    expect(render(value)).not.toContain('data-running="true"')
  }
  const cancelled = render(
    job({
      state: 'cancelled',
      nodes: [
        node({ id: 'saved', kind: 'tool', label: '查找工作', state: 'succeeded' }),
        node({ state: 'retry_wait' }),
      ],
    }),
  )
  expect(cancelled).toContain('已中断')
  expect(cancelled).toContain('已完成')
  expect(cancelled).not.toMatch(/data-running="true"|data-state="retry_wait"|秒后重试/)
})

it('does not relight a terminal attempt when a late snapshot has a larger sequence', () => {
  const terminal: JobFeedback = {
    jobId: 'job',
    attempt: 1,
    fence: 2,
    seq: 5,
    state: 'cancelled',
    stage: 'complete',
    text: '',
    error: '',
    updatedAt: '2026-09-01',
  }
  expect(acceptFeedback(terminal, { ...terminal, seq: 99, state: 'running' }, 'job')).toBe(terminal)
  expect(
    acceptFeedback(terminal, { ...terminal, attempt: 2, state: 'running' }, 'job')?.state,
  ).toBe('running')
})

it.each([
  ['needs_input', '等待补充信息'],
  ['needs_confirmation', '等待你的确认'],
  ['partial', '部分完成'],
  ['processing', '正在处理'],
  ['blocked', '暂时无法继续'],
] as const)(
  'uses the business %s outcome instead of declaring the task complete',
  (state, label) => {
    const html = renderToStaticMarkup(
      createElement(TaskProgress, {
        job: job({
          state: 'awaiting_input',
          nodes: [node({ state: 'succeeded' })],
          taskOutcome: { state, completed: [], remaining: ['请提供具体对象'], nextAction: 'reply' },
        }),
        busy: false,
        onRetry: vi.fn(),
      }),
    )
    expect(html).toContain(label)
    expect(html).not.toContain('已完成 ·')
  },
)

it('prefers the live retry state and accepts outcome-only feedback updates', () => {
  const value = job({
    state: 'running',
    taskOutcome: { state: 'blocked', completed: [], remaining: [], nextAction: 'reply' },
  })
  const html = renderToStaticMarkup(
    createElement(TaskProgress, { job: value, busy: false, onRetry: vi.fn() }),
  )
  expect(html).toContain('处理请求')
  expect(html).not.toContain('暂时无法继续')
  const base: JobFeedback = {
    jobId: 'job',
    attempt: 1,
    fence: 1,
    seq: 1,
    stage: 'complete',
    state: 'succeeded',
    text: '',
    error: '',
    updatedAt: '2026-09-28',
  }
  const changed: JobFeedback = {
    ...base,
    taskOutcome: { state: 'completed', completed: ['生成报告'], remaining: [], nextAction: 'none' },
  }
  expect(acceptFeedback(base, changed, 'job')).toBe(changed)
})

it('projects six execution nodes into two actual operations with no duplicate thoughts', () => {
  const nodes = [
    node({ id: 'm1' }),
    node({
      id: 'query',
      kind: 'tool',
      label: '查找工作',
      presentation: { type: 'operation', subject: '上线 Web' },
    }),
    node({ id: 'm2' }),
    node({
      id: 'export',
      kind: 'tool',
      label: '导出表格',
      presentation: { type: 'operation', subject: '工作清单.xlsx' },
    }),
    node({ id: 'm3' }),
    node({ id: 'm4' }),
  ].map((value) => ({ ...value, state: 'succeeded' as const }))
  const value = job({ state: 'succeeded', nodes })
  const view = progressView(value)
  expect(view.rows.map(nodeName)).toEqual(['查找工作：上线 Web', '导出表格：工作清单.xlsx'])
  expect(view.completed).toBe(2)
  const html = renderToStaticMarkup(
    createElement(TaskProgress, { job: value, busy: false, onRetry: vi.fn() }),
  )
  expect(html).toContain('已完成 · 2 项操作')
  expect(html).not.toContain('思考中')
})

it('keeps simultaneous operations, abnormal internal nodes and retry totals without counting them as success', () => {
  const nodes = [
    node({ id: 'a', kind: 'tool', label: '读取网页' }),
    node({ id: 'b', kind: 'tool', label: '读取网页' }),
    node({ id: 'internal', kind: 'review', state: 'succeeded', totalRetries: 2 }),
    node({
      id: 'blocked',
      kind: 'authorization',
      parentId: 'a',
      state: 'awaiting_input',
      error: '需要补充对象',
    }),
    node({ id: 'receipt', kind: 'tool', label: '读取操作结果', state: 'succeeded' }),
  ]
  const view = progressView(job({ nodes }))
  expect(view.parallel).toBe(true)
  expect(view.rows.map((row) => row.id)).toEqual(['a', 'b', 'internal', 'blocked'])
  expect(view.completed).toBe(0)
  expect(view.retries).toBe(2)
  const html = renderToStaticMarkup(
    createElement(TaskProgress, { job: job({ nodes }), busy: false, onRetry: vi.fn() }),
  )
  expect(html.match(/data-state="running"[^>]*data-running="true"/g)).toHaveLength(2)
  expect(html).toContain('需要补充对象')
})

it('omits successful plain-question progress but retains cancellation and final reply failure', () => {
  const render = (value: Job) =>
    renderToStaticMarkup(createElement(TaskProgress, { job: value, busy: false, onRetry: vi.fn() }))
  expect(render(job({ state: 'succeeded', nodes: [node({ state: 'succeeded' })] }))).toBe('')
  const failed = render(
    job({
      state: 'failed',
      error: '答复失败',
      nodes: [node({ kind: 'tool', state: 'succeeded' })],
    }),
  )
  expect(failed).toContain('答复失败')
  expect(failed).not.toContain('已完成 ·')
  expect(render(job({ state: 'cancelled' }))).toContain('已中断')
})
