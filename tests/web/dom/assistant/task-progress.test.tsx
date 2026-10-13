// @vitest-environment jsdom
import type { Job, TaskNode } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { JobNotice } from '../../../../apps/web/src/features/jobs/components/JobNotice'

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

it('keeps one immediate thinking label and clock through fast model phases, tools and model rounds', () => {
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
    const renderJob = (
      nodes: TaskNode[],
      state: Job['state'] = 'running',
      replyActivity?: string,
    ) => (
      <JobNotice
        job={{ ...job, nodes, state }}
        refresh={vi.fn()}
        showNodes
        replyActivity={replyActivity}
      />
    )
    const view = render(renderJob([]))
    const status = view.getByRole('status')
    expect(status.textContent).toBe('思考中 · 0 秒')
    for (const phase of ['waiting', 'thinking', 'tool_call'] as const) {
      act(() => vi.advanceTimersByTime(100))
      view.rerender(
        renderJob([{ ...model, activity: { phase, startedAt: new Date().toISOString() } }]),
      )
      expect(view.getByRole('status')).toBe(status)
      expect(status.textContent).toBe('思考中 · 0 秒')
    }
    act(() => vi.advanceTimersByTime(2700))
    expect(status.textContent).toBe('思考中 · 3 秒')
    // A fast real operation is retained, even when it completes in under a second.
    view.rerender(renderJob([{ ...model, state: 'succeeded' }, node]))
    const details = view.container.querySelector('details')!
    fireEvent.click(details.querySelector('summary')!)
    const summary = details.querySelector('summary')!
    const activity = details.querySelector('[data-reply-activity]')
    const operation = details.querySelector('[data-node-id="read"]')
    expect(summary.textContent).toBe('思考中 · 3 秒')
    expect(operation?.textContent).toContain('读取工作执行中')
    act(() => vi.advanceTimersByTime(100))
    const finished = { ...node, state: 'succeeded' as const }
    const nextModel = {
      ...model,
      id: 'model-2',
      activity: { phase: 'waiting' as const, startedAt: new Date().toISOString() },
    }
    view.rerender(renderJob([finished, nextModel]))
    expect(details.querySelector('[data-node-id="read"]')).toBe(operation)
    expect(operation?.textContent).toContain('已完成')
    expect(details.querySelector('[data-reply-activity]')).toBe(activity)
    act(() => vi.advanceTimersByTime(27900))
    expect(details.open).toBe(true)
    expect(summary.textContent).toBe('思考中 · 31 秒')
    expect(activity?.textContent).toBe('思考中31 秒')
    // An upstream answering signal alone is not yet visible answer text.
    view.rerender(
      renderJob([
        finished,
        { ...nextModel, activity: { phase: 'answering', startedAt: new Date().toISOString() } },
      ]),
    )
    expect(summary.textContent).toBe('思考中 · 31 秒')
    view.rerender(renderJob([finished, nextModel], 'running', '生成回答'))
    expect(details.open).toBe(true)
    expect(summary.textContent).toBe('生成回答 · 处理中')
    expect(details.querySelector('[data-reply-activity]')).toBe(activity)
    view.rerender(renderJob([finished, nextModel], 'cancelled'))
    expect(view.container.textContent).toContain('已中断')
    expect(view.container.querySelector('[data-running="true"]')).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  } finally {
    cleanup()
    vi.useRealTimers()
  }
})

it('shows retry and confirmation immediately and resets the clock only for a new attempt', () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-09T00:00:00Z'))
  try {
    const model: TaskNode = {
      ...node,
      id: 'model',
      kind: 'model',
      label: '思考中',
      presentation: { type: 'activity' },
    }
    const renderJob = (value: Job) => <JobNotice job={value} refresh={vi.fn()} showNodes />
    const view = render(renderJob({ ...job, nodes: [model] }))
    act(() => vi.advanceTimersByTime(2000))
    expect(view.container.textContent).toBe('思考中 · 2 秒')
    const retrying: TaskNode = {
      ...model,
      state: 'retry_wait',
      nextRetryAt: new Date(Date.now() + 3000).toISOString(),
    }
    view.rerender(renderJob({ ...job, nodes: [retrying] }))
    expect(view.container.querySelector('summary')?.textContent).toBe(
      '模型暂未响应，3 秒后重试 · 1/3',
    )
    act(() => vi.advanceTimersByTime(3000))
    view.rerender(renderJob({ ...job, nodes: [{ ...model, retries: 1, totalRetries: 1 }] }))
    expect(view.container.textContent).toBe('思考中 · 5 秒 · 第 1/3 次重试')
    view.rerender(renderJob({ ...job, nodes: [{ ...node, state: 'awaiting_confirmation' }] }))
    expect(view.container.textContent).toContain('待确认')
    expect(view.container.textContent).not.toContain('思考中')
    expect(vi.getTimerCount()).toBe(0)
    view.rerender(renderJob({ ...job, attempt: 1, fence: 2, nodes: [model] }))
    expect(view.container.textContent).toBe('思考中 · 0 秒')
    act(() => vi.advanceTimersByTime(100))
    view.rerender(
      renderJob({
        ...job,
        attempt: 1,
        fence: 2,
        state: 'succeeded',
        nodes: [{ ...model, state: 'succeeded' }],
      }),
    )
    expect(view.container.textContent).toBe('')
    expect(vi.getTimerCount()).toBe(0)
    act(() => vi.advanceTimersByTime(2000))
    expect(view.container.textContent).toBe('')
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
  expect(activity?.textContent).toBe('生成回答处理中')
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
  expect(details.querySelectorAll('li')).toHaveLength(2)
  expect(details.querySelector('summary')?.textContent).toContain('思考中 · 0 秒')
  mounted.rerender(view({ ...job, state: 'succeeded', nodes: [{ ...node, state: 'succeeded' }] }))
  expect(details.open).toBe(true)
  expect(mounted.container.querySelector('summary')?.textContent).toContain('已完成 · 1 项操作')
  expect(mounted.container.querySelector('[data-node-id="read"]')).toBe(row)
  expect(mounted.container.querySelector('details')?.open).toBe(true)
})

it('shows image generation instead of a second thinking activity, then resumes the reply status', () => {
  const images: Job['imageGeneration'] = [
    { operation: 1, state: 'ready' },
    { operation: 2, state: 'generating' },
    { operation: 3, state: 'queued' },
    { operation: 4, state: 'queued' },
  ]
  const imageNode = { ...node, label: '生成图片' }
  const view = render(
    <JobNotice
      job={{ ...job, nodes: [imageNode], imageGeneration: images }}
      refresh={vi.fn()}
      showNodes
      replyActivity="生成中"
    />,
  )
  expect(view.getByText('正在生成图片 · 已完成 1/4 张')).toBeTruthy()
  expect(view.container.querySelector('[data-reply-activity]')).toBeNull()
  expect(view.queryByText('思考中')).toBeNull()
  view.rerender(
    <JobNotice
      job={{
        ...job,
        nodes: [{ ...imageNode, state: 'succeeded' }],
        imageGeneration: images.map((slot) => ({ ...slot, state: 'ready' })),
      }}
      refresh={vi.fn()}
      showNodes
      replyActivity="生成中"
    />,
  )
  expect(view.getByText('生成回答 · 处理中')).toBeTruthy()
})
