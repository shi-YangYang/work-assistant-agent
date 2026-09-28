// @vitest-environment jsdom
import type {
  ContextUsage as Usage,
  Identity,
  Job,
  JobFeedback,
  WorkMessage,
} from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../../apps/web/src/api/client'
import { readConversationContext } from '../../../apps/web/src/features/assistant/api/requests'
import {
  ContextUsage,
  contextUsageLabel,
} from '../../../apps/web/src/features/assistant/components/ContextUsage'
import { MessageCard } from '../../../apps/web/src/features/assistant/components/MessageCard'
import { useContextUsage } from '../../../apps/web/src/features/assistant/hooks/useContextUsage'
import { createVault, deferred, identity, TestWorkspace } from './helpers'

vi.mock('@web/features/assistant/api/requests', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/features/assistant/api/requests')>()),
  readConversationContext: vi.fn(),
}))
const usage: Usage = {
  jobId: 'job',
  attempt: 1,
  fence: 2,
  seq: 4,
  model: 'vanchin/deepseek-v4.1-flash',
  usedTokens: 20000,
  contextWindow: 1048576,
  inputLimit: 1048576,
  outputReserve: 4096,
  capacitySource: '百炼官方规格',
  thresholdRatio: 0.9,
  estimated: true,
  state: 'ready',
  updatedAt: '2026-09-28T10:00:00Z',
}
const job: Job = {
  id: 'job',
  kind: 'message',
  targetId: 'message',
  state: 'running',
  phase: 'assistant',
  attempt: 1,
  fence: 2,
  error: '',
  updatedAt: usage.updatedAt,
}
const feedback: JobFeedback = {
  jobId: job.id,
  attempt: 1,
  fence: 2,
  seq: 4,
  state: 'running',
  stage: 'generating',
  text: '',
  error: '',
  updatedAt: usage.updatedAt,
  contextUsage: usage,
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(readConversationContext).mockResolvedValue({ contextUsage: null })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('shows unknown rather than zero, supports focus/touch detail, Escape and outside dismissal', () => {
  render(<ContextUsage usage={null} />)
  const button = screen.getByRole('button', { name: '上下文使用情况：尚未计算' })
  fireEvent.focus(button)
  expect(screen.getByRole('tooltip').textContent).toContain('尚未计算')
  fireEvent.click(button)
  expect(screen.getByRole('dialog', { name: '上下文使用情况' })).toBeTruthy()
  expect(screen.queryByText('0%')).toBeNull()
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(button)
  fireEvent.click(button)
  fireEvent.pointerDown(document.body)
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('shows real 1M capacity, output reserve, unknown capacity and no premature 90% rounding', () => {
  const view = render(<ContextUsage usage={usage} />)
  fireEvent.click(screen.getByRole('button', { name: '上下文使用情况：约 1%' }))
  expect(screen.getByText('1,048,576 tokens')).toBeTruthy()
  expect(screen.getByText('4,096 tokens')).toBeTruthy()
  expect(contextUsageLabel({ ...usage, usedTokens: 943718 })).toBe('约 89%')
  expect(contextUsageLabel({ ...usage, usedTokens: 1048577 })).toBe('约 100%')
  view.rerender(<ContextUsage usage={{ ...usage, contextWindow: null }} />)
  expect(screen.getByRole('button', { name: '上下文使用情况：窗口大小未配置' })).toBeTruthy()
  expect(screen.getByText('未配置')).toBeTruthy()
  expect(screen.queryByText('约 0%')).toBeNull()
})

it('renders compaction progress and persisted before/after without adding a toast', () => {
  const view = render(<ContextUsage usage={{ ...usage, state: 'compacting' }} />)
  fireEvent.click(screen.getByRole('button', { name: '上下文使用情况：正在压缩上下文' }))
  expect(screen.getByText('正在压缩上下文')).toBeTruthy()
  view.rerender(<ContextUsage usage={{ ...usage, state: 'retry_wait' }} />)
  expect(screen.getByText('压缩重试中')).toBeTruthy()
  view.rerender(
    <ContextUsage
      usage={{ ...usage, compactionId: 'compact', beforeTokens: 950000, afterTokens: 20000 }}
    />,
  )
  expect(screen.getByText('上下文已压缩 · 950,000 → 20,000 tokens')).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})

function Hook({
  conversationId = 'first',
  latestJob = job,
  incoming,
}: {
  conversationId?: string
  latestJob?: Job
  incoming?: JobFeedback
}) {
  const context = useContextUsage(conversationId, latestJob)
  return (
    <>
      <ContextUsage usage={context.usage} unavailable={context.unavailable} />
      <button onClick={() => context.receive(latestJob, incoming ?? feedback)}>反馈</button>
    </>
  )
}
const vault = createVault()
function viewHook(props: Parameters<typeof Hook>[0] = {}, account: Identity = identity) {
  return (
    <TestWorkspace vault={vault} account={account}>
      <Hook {...props} />
    </TestWorkspace>
  )
}

it('restores once and rejects stale sequence, attempt, lease and slow HTTP snapshots', async () => {
  const request = deferred<{ contextUsage: Usage | null }>()
  vi.mocked(readConversationContext).mockReturnValue(request.promise)
  const view = render(viewHook())
  fireEvent.click(screen.getByText('反馈'))
  expect(screen.getByRole('button', { name: '上下文使用情况：约 1%' })).toBeTruthy()
  await act(async () => request.resolve({ contextUsage: { ...usage, seq: 1, usedTokens: 900000 } }))
  for (const old of [
    { ...feedback, contextUsage: { ...usage, seq: 2, usedTokens: 900000 } },
    {
      ...feedback,
      attempt: 0,
      contextUsage: { ...usage, attempt: 0, seq: 20, usedTokens: 900000 },
    },
    { ...feedback, fence: 1, contextUsage: { ...usage, fence: 1, seq: 20, usedTokens: 900000 } },
  ]) {
    view.rerender(viewHook({ incoming: old }))
    fireEvent.click(screen.getByText('反馈'))
    expect(screen.getByRole('button', { name: '上下文使用情况：约 1%' })).toBeTruthy()
  }
  expect(readConversationContext).toHaveBeenCalledTimes(1)
  view.rerender(
    viewHook({
      latestJob: { ...job, attempt: 2, contextUsage: null },
      incoming: { ...feedback, attempt: 2, contextUsage: null },
    }),
  )
  expect(screen.getByRole('button', { name: '上下文使用情况：尚未计算' })).toBeTruthy()
  fireEvent.click(screen.getByText('反馈'))
  view.rerender(viewHook({ incoming: feedback }))
  fireEvent.click(screen.getByText('反馈'))
  expect(screen.getByRole('button', { name: '上下文使用情况：尚未计算' })).toBeTruthy()
})

it('isolates account and conversation immediately and drops late requests', async () => {
  const old = deferred<{ contextUsage: Usage | null }>()
  vi.mocked(readConversationContext).mockReturnValueOnce(old.promise)
  const view = render(viewHook())
  view.rerender(viewHook({ conversationId: 'second', latestJob: { ...job, id: 'next' } }))
  await act(async () => old.resolve({ contextUsage: usage }))
  expect(screen.getByRole('button', { name: '上下文使用情况：尚未计算' })).toBeTruthy()
  view.rerender(viewHook())
  fireEvent.click(screen.getByText('反馈'))
  expect(screen.getByRole('button', { name: '上下文使用情况：约 1%' })).toBeTruthy()
  view.rerender(viewHook({}, { ...identity, member: { ...identity.member, id: 'other' } }))
  expect(screen.getByRole('button', { name: '上下文使用情况：尚未计算' })).toBeTruthy()
  await act(async () => {})
})

it('keeps a failed restore local to the icon and recovers online without an extra SSE', async () => {
  const eventSource = vi.fn()
  vi.stubGlobal('EventSource', eventSource)
  vi.mocked(readConversationContext)
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue({ contextUsage: usage })
  render(viewHook())
  await screen.findByRole('button', { name: '上下文使用情况：暂不可用' })
  expect(screen.queryByRole('alert')).toBeNull()
  await act(async () => window.dispatchEvent(new Event('online')))
  expect(screen.getByRole('button', { name: '上下文使用情况：约 1%' })).toBeTruthy()
  expect(eventSource).not.toHaveBeenCalled()
})

it('reuses the message card subscription to update the composer and keeps its final snapshot', async () => {
  const sources: EventTarget[] = []
  class Source extends EventTarget {
    close = vi.fn()
    constructor() {
      super()
      sources.push(this)
    }
  }
  vi.stubGlobal('EventSource', Source)
  function Chat() {
    const [current, setCurrent] = useState(job)
    const context = useContextUsage('first', current)
    const message = {
      id: 'message',
      conversationId: 'first',
      ownerId: 'owner',
      text: '执行任务',
      reply: '',
      createdAt: usage.updatedAt,
      attachments: [],
      drafts: [],
      suggestions: [],
      job: current,
    } as unknown as WorkMessage
    return (
      <>
        <MessageCard
          message={message}
          own
          onChange={() => setCurrent({ ...current, state: 'succeeded', contextUsage: usage })}
          onContextUpdate={context.receive}
        />
        <ContextUsage usage={context.usage} />
      </>
    )
  }
  render(
    <TestWorkspace vault={createVault()}>
      <MemoryRouter>
        <Chat />
      </MemoryRouter>
    </TestWorkspace>,
  )
  await waitFor(() => expect(sources).toHaveLength(1))
  act(() =>
    sources[0].dispatchEvent(new MessageEvent('snapshot', { data: JSON.stringify(feedback) })),
  )
  expect(screen.getByRole('button', { name: '上下文使用情况：约 1%' })).toBeTruthy()
  act(() =>
    sources[0].dispatchEvent(
      new MessageEvent('snapshot', {
        data: JSON.stringify({ ...feedback, state: 'succeeded', seq: 5 }),
      }),
    ),
  )
  expect(screen.getByRole('button', { name: '上下文使用情况：约 1%' })).toBeTruthy()
  expect(sources).toHaveLength(1)
})

it('clears restored metrics after access is revoked, without leaking a previous snapshot', async () => {
  vi.mocked(readConversationContext)
    .mockResolvedValueOnce({ contextUsage: usage })
    .mockRejectedValueOnce(new ApiError(403, 'forbidden', '无权限', 'forbidden'))
  render(viewHook())
  await screen.findByRole('button', { name: '上下文使用情况：约 1%' })
  await act(async () => window.dispatchEvent(new Event('online')))
  expect(screen.getByRole('button', { name: '上下文使用情况：暂不可用' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '上下文使用情况：约 1%' })).toBeNull()
})

it('leaves compaction when a newer terminal/retry snapshot arrives and rejects late active events', async () => {
  const compacting = { ...feedback, contextUsage: { ...usage, state: 'compacting' as const } }
  const view = render(viewHook({ incoming: compacting }))
  fireEvent.click(screen.getByText('反馈'))
  expect(screen.getByRole('button', { name: '上下文使用情况：正在压缩上下文' })).toBeTruthy()
  for (const [seq, state, title] of [
    [5, 'retry_wait', '压缩重试中'],
    [6, 'compacting', '正在压缩上下文'],
    [7, 'failed', '上下文处理未完成'],
  ] as const) {
    view.rerender(
      viewHook({ incoming: { ...feedback, seq, contextUsage: { ...usage, seq, state } } }),
    )
    fireEvent.click(screen.getByText('反馈'))
    expect(screen.getByRole('button', { name: `上下文使用情况：${title}` })).toBeTruthy()
  }
  view.rerender(viewHook({ incoming: compacting }))
  fireEvent.click(screen.getByText('反馈'))
  expect(screen.getByRole('button', { name: '上下文使用情况：上下文处理未完成' })).toBeTruthy()
  await act(async () => {})
})
