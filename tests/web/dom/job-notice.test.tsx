// @vitest-environment jsdom
import type { Job } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { startTransition, StrictMode, Suspense, useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { retryJob } from '../../../apps/web/src/features/jobs/api/requests'
import { JobNotice } from '../../../apps/web/src/features/jobs/components/JobNotice'
import { deferred, dialogs } from './helpers'

vi.mock('@web/features/jobs/api/requests', () => ({ retryJob: vi.fn() }))

const first: Job = {
  id: 'first',
  kind: 'report',
  targetId: 'report-first',
  state: 'failed',
  phase: 'report',
  error: '第一个任务失败',
  attempt: 1,
  fence: 1,
  updatedAt: '2026-09-25T00:00:00Z',
}
const second: Job = { ...first, id: 'second', targetId: 'report-second', error: '第二个任务失败' }
const outcomes = ['success', 'failure'] as const
async function finish(
  request: ReturnType<typeof deferred<Job>>,
  outcome: (typeof outcomes)[number],
  job = first,
) {
  await act(async () => {
    if (outcome === 'success') request.resolve({ ...job, state: 'queued', attempt: 2 })
    else request.reject(new Error('旧任务请求失败'))
  })
}

beforeEach(() => {
  vi.resetAllMocks()
  dialogs()
})
afterEach(cleanup)

it.each([true, false])('preserves manually chosen expansion %s across task updates', (expanded) => {
  const node: NonNullable<Job['nodes']>[number] = {
    id: 'thinking',
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
  }
  const job: Job = { ...first, kind: 'message', state: 'running', error: '', nodes: [node] }
  const renderJob = (value: Job) => <JobNotice job={value} refresh={vi.fn()} showNodes />
  const mounted = render(renderJob(job))
  const details = () => mounted.container.querySelector('details')!
  const toggle = () => {
    fireEvent.click(details().querySelector('summary')!)
    fireEvent(details(), new Event('toggle'))
  }
  toggle()
  if (!expanded) toggle()
  expect(details().open).toBe(expanded)

  for (const state of ['running', 'retry_wait', 'succeeded'] as const) {
    mounted.rerender(
      renderJob({
        ...job,
        state: state === 'succeeded' ? 'succeeded' : 'running',
        updatedAt: `2026-09-25T00:00:0${state === 'running' ? 1 : state === 'retry_wait' ? 2 : 3}Z`,
        nodes: [
          { ...node, state: 'succeeded' },
          { ...node, id: 'search', kind: 'tool', label: '搜索公开资料', state },
        ],
      }),
    )
    expect(details().open).toBe(expanded)
    expect(details().textContent).toContain('搜索公开资料')
  }
  mounted.rerender(renderJob({ ...job, id: 'another-job' }))
  expect(details().open).toBe(false)
})

it.each(outcomes)(
  'makes the new report actionable and ignores the old retry %s',
  async (outcome) => {
    const oldRequest = deferred<Job>(),
      nextRequest = deferred<Job>()
    const oldRefresh = vi.fn(),
      nextRefresh = vi.fn()
    vi.mocked(retryJob)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(nextRequest.promise)
    const mounted = render(<JobNotice job={first} refresh={oldRefresh} />)
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    mounted.rerender(<JobNotice job={second} refresh={nextRefresh} />)
    expect(screen.getByText(second.error)).toBeTruthy()
    expect((screen.getByRole('button', { name: '重试' }) as HTMLButtonElement).disabled).toBe(false)

    await finish(oldRequest, outcome)
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByText('旧任务请求失败')).toBeNull()
    expect(screen.getByText(second.error)).toBeTruthy()
    expect(oldRefresh).not.toHaveBeenCalled()
    expect(nextRefresh).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(retryJob).toHaveBeenLastCalledWith(second, { useCurrentConfig: true })
    await finish(nextRequest, 'success', second)
    expect(nextRefresh).toHaveBeenCalledTimes(1)
  },
)

it.each(outcomes)(
  'keeps the current document request locked after the old retry %s',
  async (outcome) => {
    const oldRequest = deferred<Job>(),
      nextRequest = deferred<Job>()
    const refresh = vi.fn()
    const document = { ...second, kind: 'document' as const }
    vi.mocked(retryJob)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(nextRequest.promise)
    const mounted = render(<JobNotice job={first} refresh={refresh} />)
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    mounted.rerender(<JobNotice job={document} refresh={refresh} />)
    fireEvent.click(screen.getByRole('button', { name: '重试处理' }))
    expect(retryJob).toHaveBeenLastCalledWith(document, {})

    await finish(oldRequest, outcome)
    for (const button of screen.getAllByRole('button')) {
      expect((button as HTMLButtonElement).disabled).toBe(true)
      fireEvent.click(button)
    }
    expect(retryJob).toHaveBeenCalledTimes(2)
    expect(screen.getByText(document.error)).toBeTruthy()
    expect(screen.queryByText('旧任务请求失败')).toBeNull()
    expect(refresh).not.toHaveBeenCalled()

    await finish(nextRequest, 'success', document)
    expect(refresh).toHaveBeenCalledTimes(1)
    expect((screen.getByRole('button', { name: '重试处理' }) as HTMLButtonElement).disabled).toBe(
      false,
    )
  },
)

it('keeps the current report queued until its own request fails', async () => {
  const oldRequest = deferred<Job>(),
    nextRequest = deferred<Job>()
  const refresh = vi.fn()
  vi.mocked(retryJob)
    .mockReturnValueOnce(oldRequest.promise)
    .mockReturnValueOnce(nextRequest.promise)
  const mounted = render(<JobNotice job={first} refresh={refresh} />)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  mounted.rerender(<JobNotice job={second} refresh={refresh} />)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await finish(oldRequest, 'failure')
  expect(screen.getByRole('status').textContent).toContain('排队')
  expect(screen.queryByRole('button')).toBeNull()
  expect(refresh).not.toHaveBeenCalled()

  await act(async () => nextRequest.reject(new Error('当前报告模型不可用')))
  expect(screen.getByText('当前报告模型不可用')).toBeTruthy()
  expect(screen.getAllByRole('button')).toHaveLength(1)
  expect((screen.getByRole('button', { name: '重试' }) as HTMLButtonElement).disabled).toBe(false)
})

it.each([
  ['attempt', { attempt: 2 }],
  ['fence', { fence: 2 }],
  ['updatedAt', { updatedAt: '2026-09-25T00:01:00Z' }],
  ['state', { state: 'awaiting_retry' as const }],
] as const)('invalidates a pending retry when the same job changes %s', async (_, change) => {
  const request = deferred<Job>(),
    refresh = vi.fn()
  vi.mocked(retryJob).mockReturnValueOnce(request.promise)
  const mounted = render(<JobNotice job={first} refresh={refresh} />)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  mounted.rerender(
    <JobNotice job={{ ...first, ...change, error: '当前执行失败' }} refresh={refresh} />,
  )
  expect(screen.getByText('当前执行失败')).toBeTruthy()
  expect((screen.getByRole('button', { name: '重试' }) as HTMLButtonElement).disabled).toBe(false)
  await finish(request, 'failure')
  expect(screen.getByText('当前执行失败')).toBeTruthy()
  expect(screen.queryByText('旧任务请求失败')).toBeNull()
  expect(refresh).not.toHaveBeenCalled()
})

it('does not revive an old session when the source returns to the same failed snapshot', async () => {
  const request = deferred<Job>(),
    refresh = vi.fn()
  vi.mocked(retryJob).mockReturnValueOnce(request.promise)
  const mounted = render(<JobNotice job={first} refresh={refresh} />)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  mounted.rerender(<JobNotice job={{ ...first, state: 'running' }} refresh={refresh} />)
  expect(screen.getByRole('status').textContent).toContain('正在生成报告')
  mounted.rerender(<JobNotice job={first} refresh={refresh} />)
  await finish(request, 'success')
  expect(screen.getByText(first.error)).toBeTruthy()
  expect((screen.getByRole('button', { name: '重试' }) as HTMLButtonElement).disabled).toBe(false)
  expect(refresh).not.toHaveBeenCalled()
})

it('discards a document confirmation and previous request error when changing jobs', async () => {
  vi.mocked(retryJob).mockRejectedValueOnce(new Error('请求失败'))
  const document = { ...first, kind: 'document' as const }
  const mounted = render(<JobNotice job={document} refresh={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: '重试处理' }))
  expect(await screen.findByText('请求失败')).toBeTruthy()
  mounted.rerender(<JobNotice job={{ ...document, state: 'awaiting_retry' }} refresh={vi.fn()} />)
  expect(screen.queryByText('请求失败')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '重试处理' }))
  expect(screen.getByRole('dialog')).toBeTruthy()
  mounted.rerender(<JobNotice job={{ ...second, kind: 'document' }} refresh={vi.fn()} />)
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByText(second.error)).toBeTruthy()
  expect(screen.getByRole('button', { name: '使用当前配置重新处理' })).toBeTruthy()
})

it.each(outcomes)('ignores assistant retry %s callbacks after unmount', async (outcome) => {
  const request = deferred<Job>(),
    refresh = vi.fn(),
    onRetryJob = vi.fn()
  const message = { ...first, kind: 'message' as const }
  vi.mocked(retryJob).mockReturnValueOnce(request.promise)
  const mounted = render(
    <JobNotice job={message} refresh={refresh} onRetryJob={onRetryJob} showNodes />,
  )
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(onRetryJob).toHaveBeenCalledTimes(1)
  mounted.unmount()
  await finish(request, outcome, message)
  expect(onRetryJob).toHaveBeenCalledTimes(1)
  expect(refresh).not.toHaveBeenCalled()
})

it.each(outcomes)(
  'preserves the assistant optimistic parent update through retry %s',
  async (outcome) => {
    const request = deferred<Job>(),
      refresh = vi.fn()
    const message = { ...first, kind: 'message' as const }
    vi.mocked(retryJob).mockReturnValueOnce(request.promise)
    function Parent() {
      const [retried, setRetried] = useState<Job | null>(null)
      return (
        <JobNotice job={retried ?? message} refresh={refresh} onRetryJob={setRetried} showNodes />
      )
    }
    render(<Parent />)
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(screen.getByRole('status').textContent).toContain('排队')
    expect(retryJob).toHaveBeenCalledExactlyOnceWith(message, {})
    await finish(request, outcome, message)
    if (outcome === 'success') {
      expect(refresh).toHaveBeenCalledTimes(1)
      expect(screen.getByRole('status').textContent).toContain('排队')
    } else {
      expect(screen.getByText('旧任务请求失败')).toBeTruthy()
      expect((screen.getByRole('button', { name: '重试' }) as HTMLButtonElement).disabled).toBe(
        false,
      )
      expect(refresh).not.toHaveBeenCalled()
    }
  },
)

it.each(outcomes)(
  'keeps the committed retry owner while a different job render suspends (%s)',
  async (outcome) => {
    const request = deferred<Job>(),
      navigation = deferred<void>(),
      refresh = vi.fn(),
      attemptedNavigation = vi.fn()
    vi.mocked(retryJob).mockReturnValueOnce(request.promise)
    function PendingNavigation({ pending }: { pending: boolean }) {
      if (pending) {
        attemptedNavigation()
        throw navigation.promise
      }
      return null
    }
    function Parent() {
      const [job, setJob] = useState(first)
      return (
        <>
          <button onClick={() => startTransition(() => setJob(second))}>切换任务</button>
          <button onClick={() => setJob(first)}>取消切换</button>
          <Suspense fallback={<p>加载任务</p>}>
            <JobNotice job={job} refresh={refresh} />
            <PendingNavigation pending={job === second} />
          </Suspense>
        </>
      )
    }
    render(
      <StrictMode>
        <Parent />
      </StrictMode>,
    )
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    fireEvent.click(screen.getByRole('button', { name: '切换任务' }))
    expect(attemptedNavigation).toHaveBeenCalled()
    expect(screen.queryByText('加载任务')).toBeNull()
    await finish(request, outcome)
    fireEvent.click(screen.getByRole('button', { name: '取消切换' }))
    if (outcome === 'success') {
      expect(refresh).toHaveBeenCalledTimes(1)
      expect(screen.getByRole('status').textContent).toContain('排队')
    } else {
      expect(screen.getByText('旧任务请求失败')).toBeTruthy()
      expect((screen.getByRole('button', { name: '重试' }) as HTMLButtonElement).disabled).toBe(
        false,
      )
    }
  },
)
