// @vitest-environment jsdom
import type { Job, TaskNode } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { JobNotice } from '../../../apps/web/src/features/jobs/components/JobNotice'

const node: TaskNode = {
  id: 'read',
  parentId: null,
  kind: 'tool',
  label: '读取工作',
  state: 'running',
  attempts: 1,
  maxAttempts: 4,
  retries: 0,
  totalRetries: 0,
  round: 0,
  nextRetryAt: null,
  error: '',
  errorCode: '',
  canRetry: false,
  presentation: { type: 'operation' },
}
const job: Job = {
  id: 'job',
  targetId: 'message',
  kind: 'message',
  state: 'running',
  phase: 'assistant',
  error: '',
  updatedAt: '2026-01-01',
  attempt: 0,
  fence: 1,
  nodes: [node],
}
afterEach(cleanup)

it('shows real model phases with a local clock, preserves expanded steps and stops on termination', () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-09T00:00:00Z'))
  try {
    const model: TaskNode = {
      ...node,
      id: 'model',
      kind: 'model',
      label: '等待模型响应',
      presentation: { type: 'activity' },
      activity: { phase: 'waiting', startedAt: new Date().toISOString() },
    }
    const renderJob = (nodes: TaskNode[], state: Job['state'] = 'running') => (
      <JobNotice job={{ ...job, nodes, state }} refresh={vi.fn()} showNodes />
    )
    const view = render(renderJob([model]))
    expect(view.container.textContent).toBe('等待模型响应 · 0 秒')
    act(() => vi.advanceTimersByTime(3000))
    expect(view.container.textContent).toBe('等待模型响应 · 3 秒')
    const thinking = {
      ...model,
      activity: { phase: 'thinking' as const, startedAt: new Date().toISOString() },
    }
    const finished = { ...node, state: 'succeeded' as const }
    view.rerender(renderJob([finished, thinking]))
    const details = view.container.querySelector('details')!
    fireEvent.click(details.querySelector('summary')!)
    act(() => vi.advanceTimersByTime(28000))
    expect(details.open).toBe(true)
    expect(details.querySelector('summary')?.textContent).toBe('思考中 · 28 秒')
    expect(details.querySelector('[data-reply-activity]')?.textContent).toBe('思考中28 秒')
    const answering = {
      ...model,
      activity: { phase: 'answering' as const, startedAt: new Date().toISOString() },
    }
    view.rerender(renderJob([finished, answering]))
    expect(details.open).toBe(true)
    expect(details.querySelector('summary')?.textContent).toBe('生成回答 · 0 秒')
    view.rerender(renderJob([finished, answering], 'cancelled'))
    expect(view.container.textContent).toContain('已中断')
    expect(view.container.querySelector('[data-running="true"]')).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  } finally {
    cleanup()
    vi.useRealTimers()
  }
})

it('moves reply generation into the existing progress without losing expansion or inflating operation counts', () => {
  const value = { ...job, nodes: [{ ...node, state: 'succeeded' as const }] }
  const view = render(
    <JobNotice job={value} refresh={vi.fn()} showNodes replyActivity="生成回答" />,
  )
  const details = view.container.querySelector('details')!
  fireEvent.click(details.querySelector('summary')!)
  const activity = details.querySelector('[data-reply-activity]')
  expect(details.open).toBe(true)
  expect(activity?.textContent).toBe('生成回答处理中')
  expect(details.querySelectorAll('li')).toHaveLength(2)
  view.rerender(
    <JobNotice
      job={{ ...value, updatedAt: '2026-01-02' }}
      refresh={vi.fn()}
      showNodes
      replyActivity="核对并保存回复"
    />,
  )
  expect(view.container.querySelector('details')).toBe(details)
  expect(details.open).toBe(true)
  expect(details.querySelector('[data-reply-activity]')).toBe(activity)
  expect(activity?.textContent).toBe('核对并保存回复处理中')
  view.rerender(<JobNotice job={{ ...value, state: 'succeeded' }} refresh={vi.fn()} showNodes />)
  expect(details.open).toBe(true)
  expect(details.querySelector('summary')?.textContent).toBe('已完成 · 1 项操作')
  expect(details.querySelector('[data-reply-activity]')).toBeNull()
})

it.each(['cancelled', 'awaiting_retry'] as const)(
  'stops the reply activity on %s even if its last label is still present',
  (state) => {
    const view = render(
      <JobNotice
        job={{ ...job, state, error: state === 'awaiting_retry' ? '服务中断' : '' }}
        refresh={vi.fn()}
        showNodes
        replyActivity="生成回答"
      />,
    )
    expect(view.container.querySelector('[data-reply-activity]')).toBeNull()
    expect(view.container.querySelector('[data-running="true"]')).toBeNull()
    expect(view.container.textContent).toContain(state === 'cancelled' ? '已中断' : '服务中断')
  },
)

it('keeps the same expanded operation row when the subject resolves and processing advances', () => {
  const view = (value: Job) => <JobNotice job={value} refresh={vi.fn()} showNodes />
  const mounted = render(view(job))
  const details = mounted.container.querySelector('details')!
  fireEvent.click(details.querySelector('summary')!)
  const row = mounted.container.querySelector('[data-node-id="read"]')
  mounted.rerender(
    view({
      ...job,
      updatedAt: '2026-01-02',
      nodes: [
        { ...node, state: 'succeeded', presentation: { type: 'operation', subject: '登录页优化' } },
        {
          ...node,
          id: 'model',
          kind: 'model',
          label: '整理工具结果',
          presentation: { type: 'activity' },
        },
      ],
    }),
  )
  expect(mounted.container.querySelector('details')).toBe(details)
  expect(details.open).toBe(true)
  expect(mounted.container.querySelector('[data-node-id="read"]')).toBe(row)
  expect(row?.textContent).toContain('读取工作：登录页优化')
  expect(details.querySelectorAll('li')).toHaveLength(1)
  expect(details.querySelector('summary')?.textContent).toContain('整理工具结果')
  mounted.rerender(view({ ...job, state: 'succeeded', nodes: [{ ...node, state: 'succeeded' }] }))
  expect(details.open).toBe(true)
  expect(mounted.container.querySelector('summary')?.textContent).toContain('已完成 · 1 项操作')
  expect(mounted.container.querySelector('[data-node-id="read"]')).toBe(row)
  expect(mounted.container.querySelector('details')?.open).toBe(true)
})
