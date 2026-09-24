import type { Job, JobFeedback, TaskNode } from '@paa/api-contracts'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi } from 'vitest'
import { acceptFeedback, visibleFeedback } from '../../apps/web/src/api/job-feedback'
import { JobNotice } from '../../apps/web/src/features/jobs/components/JobNotice'
import { nodeStatus } from '../../apps/web/src/features/jobs/components/TaskNode'
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
  expect(running).toContain('<summary>')
  expect(running).toContain('aria-label="处理步骤"')
  expect(running).not.toContain('aria-live')
  const complete = render(
    job({
      state: 'succeeded',
      nodes: [node({ state: 'succeeded', attempts: 3, retries: 2, totalRetries: 2 })],
    }),
  )
  expect(complete).toContain('已完成 1 个步骤 · 自动重试 2 次')
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

it('requires explicit assistant opt-in and preserves other JobNotice presentation', () => {
  const ordinary = renderToStaticMarkup(createElement(JobNotice, { job: job(), refresh: vi.fn() }))
  expect(ordinary).not.toContain('处理步骤')
  const assistant = renderToStaticMarkup(
    createElement(JobNotice, { job: job(), refresh: vi.fn(), showNodes: true }),
  )
  expect(assistant).toContain('处理步骤')
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
