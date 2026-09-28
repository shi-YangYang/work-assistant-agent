// @vitest-environment jsdom
import type { Identity, Job, JobFeedback, WorkMessage } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../../apps/web/src/api/client'
import {
  readActiveAssistantJob,
  sendMessage,
} from '../../../apps/web/src/features/assistant/api/requests'
import { cancelJob, retryJob } from '../../../apps/web/src/features/jobs/api/requests'
import { MessageCard } from '../../../apps/web/src/features/assistant/components/MessageCard'
import { ConversationChat } from '../../../apps/web/src/features/assistant/components/ConversationChat'
import { useAssistantTask } from '../../../apps/web/src/features/assistant/hooks/useAssistantTask'
import { useConversationPersona } from '../../../apps/web/src/features/assistant/hooks/useConversationPersona'
import { createVault, deferred, dialogs, identity, TestWorkspace } from './helpers'

vi.mock('@web/features/assistant/api/requests', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/features/assistant/api/requests')>()),
  readActiveAssistantJob: vi.fn(),
  sendMessage: vi.fn(),
}))
vi.mock('@web/features/jobs/api/requests', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/features/jobs/api/requests')>()),
  cancelJob: vi.fn(),
  retryJob: vi.fn(),
}))
const running: Job = {
  id: 'job',
  targetId: 'message',
  kind: 'message',
  state: 'running',
  attempt: 1,
  fence: 2,
  phase: 'assistant',
  stage: 'generating',
  error: '',
  updatedAt: '2026-09-01T01:00:00Z',
}
const message = (job: Job): WorkMessage =>
  ({
    id: job.targetId,
    conversationId: 'first',
    ownerId: 'owner',
    text: '原消息',
    reply: '',
    createdAt: '2026-09-01',
    attachments: [],
    drafts: [],
    suggestions: [],
    job,
  }) as unknown as WorkMessage
let history: WorkMessage[] = []
const sources: Source[] = []
class Source extends EventTarget {
  close = vi.fn()
  constructor() {
    super()
    sources.push(this)
  }
}
const feedback = (patch: Partial<JobFeedback> = {}): JobFeedback => ({
  jobId: running.id,
  attempt: 1,
  fence: 2,
  seq: 1,
  state: 'running',
  stage: 'generating',
  text: '',
  error: '',
  updatedAt: running.updatedAt,
  ...patch,
})
beforeEach(() => {
  dialogs()
  vi.resetAllMocks()
  sources.length = 0
  history = []
  vi.stubGlobal('EventSource', Source)
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.includes('/messages?')
              ? { items: history, nextCursor: null }
              : url.includes('/context-usage')
                ? { contextUsage: history.at(-1)?.job?.contextUsage ?? null }
                : { items: [], nextCursor: null },
          ),
        ),
    ),
  )
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: null })
  localStorage.clear()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
function Chat({ initial = 'first' }: { initial?: string }) {
  const [id, setId] = useState(initial || undefined)
  const persona = useConversationPersona(id, null, vi.fn())
  return (
    <ConversationChat
      conversationId={id}
      personaId="professional"
      interaction={persona.interaction}
      onSent={setId}
    />
  )
}
function view(initial = 'first', vault = createVault()) {
  return render(
    <TestWorkspace vault={vault}>
      <MemoryRouter>
        <Chat initial={initial} />
      </MemoryRouter>
    </TestWorkspace>,
  )
}
const input = () => screen.getByRole('textbox', { name: '工作消息' }) as HTMLTextAreaElement
const type = (value: string) => fireEvent.change(input(), { target: { value } })

it('locks before history loads, permits the next draft and attachments, and preserves them through cancellation', async () => {
  const restore = deferred<{ job: Job | null }>()
  vi.mocked(readActiveAssistantJob)
    .mockReturnValueOnce(restore.promise)
    .mockResolvedValue({ job: running })
  const vault = createVault()
  view('first', vault)
  type('下一条草稿')
  expect(
    (screen.getByRole('button', { name: '正在恢复处理状态' }) as HTMLButtonElement).disabled,
  ).toBe(true)
  fireEvent.keyDown(input(), { key: 'Enter' })
  expect(sendMessage).not.toHaveBeenCalled()
  await act(async () => restore.resolve({ job: running }))
  const button = screen.getByRole('button', { name: '中断' })
  const context = screen.getByRole('button', { name: /^上下文使用情况/ })
  expect(input().readOnly).toBe(false)
  expect((screen.getByRole('button', { name: '添加附件' }) as HTMLButtonElement).disabled).toBe(
    false,
  )
  expect((screen.getByRole('button', { name: '录制语音' }) as HTMLButtonElement).disabled).toBe(
    false,
  )
  fireEvent.keyDown(input(), { key: 'Enter' })
  expect(sendMessage).not.toHaveBeenCalled()
  const request = deferred<Job>()
  vi.mocked(cancelJob).mockReturnValue(request.promise)
  fireEvent.click(button)
  fireEvent.click(button)
  expect(cancelJob).toHaveBeenCalledExactlyOnceWith(running)
  type('编辑后的下一条')
  expect(screen.getByRole('button', { name: '中断中' })).toBe(button)
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: null })
  await act(async () => request.resolve({ ...running, state: 'cancelled', fence: 3 }))
  await screen.findByRole('button', { name: '发送' })
  expect(input().value).toBe('编辑后的下一条')
  expect(screen.getByRole('button', { name: /^上下文使用情况/ })).toBe(context)
  expect(vault.getSnapshot()['composer:first']).toMatchObject({ text: '编辑后的下一条' })
})

it('keeps interruption available after a network error and requires server confirmation', async () => {
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: running })
  vi.mocked(cancelJob).mockRejectedValueOnce(new Error('网络中断'))
  view()
  fireEvent.click(await screen.findByRole('button', { name: '中断' }))
  await screen.findByText('网络中断')
  type('继续草稿')
  fireEvent.keyDown(input(), { key: 'Enter' })
  expect(sendMessage).not.toHaveBeenCalled()
  expect((screen.getByRole('button', { name: '中断' }) as HTMLButtonElement).disabled).toBe(false)
})

it('registers acceptance before history refresh and keeps a new conversation locked across routing', async () => {
  const restore = deferred<{ job: Job | null }>()
  vi.mocked(readActiveAssistantJob).mockReturnValue(restore.promise)
  vi.mocked(sendMessage).mockResolvedValue({
    conversationId: 'created',
    messageId: 'message',
    jobId: 'job',
  })
  view('')
  type('第一条')
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => expect(input().value).toBe(''))
  type('第二条')
  fireEvent.keyDown(input(), { key: 'Enter' })
  expect(sendMessage).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('button', { name: '发送' })).toBeNull()
  await act(async () => restore.resolve({ job: running }))
  await screen.findByRole('button', { name: '中断' })
})

it('keeps the context estimate and ring through sending and acceptance before the next estimate', async () => {
  history = [
    message({
      ...running,
      state: 'succeeded',
      contextUsage: {
        jobId: running.id,
        attempt: 1,
        fence: 2,
        seq: 4,
        model: 'model',
        capacitySource: '测试容量',
        usedTokens: 300,
        contextWindow: 1000,
        inputLimit: 1000,
        outputReserve: 100,
        thresholdRatio: 0.9,
        estimated: true,
        state: 'ready',
        updatedAt: running.updatedAt,
      },
    }),
  ]
  const submission = deferred<Awaited<ReturnType<typeof sendMessage>>>()
  vi.mocked(sendMessage).mockReturnValue(submission.promise)
  view()
  const button = await screen.findByRole('button', { name: '上下文使用情况：约 30%' })
  const ring = button.querySelector('circle[pathLength]')
  await screen.findByRole('button', { name: '发送' })
  vi.mocked(readActiveAssistantJob).mockReturnValue(deferred<{ job: Job | null }>().promise)
  type('继续处理')
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  expect(screen.getByRole('button', { name: '上下文使用情况：约 30%' })).toBe(button)
  await act(async () =>
    submission.resolve({ conversationId: 'first', messageId: 'next-message', jobId: 'next' }),
  )
  await screen.findByRole('button', { name: '中断' })
  expect(screen.getByRole('button', { name: '上下文使用情况：约 30%' })).toBe(button)
  expect(button.querySelector('circle[pathLength]')).toBe(ring)
})

it('confirms an unknown submission verbatim even when that job has already become active', async () => {
  vi.mocked(sendMessage)
    .mockRejectedValueOnce(new Error('提交结果未知'))
    .mockResolvedValueOnce({ conversationId: 'first', messageId: 'message', jobId: 'job' })
  view()
  await screen.findByRole('button', { name: '发送' })
  type('原请求')
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByRole('button', { name: '原样重试，确认结果' })
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: running })
  await act(async () => window.dispatchEvent(new Event('focus')))
  fireEvent.click(screen.getByRole('button', { name: '原样重试，确认结果' }))
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2))
  expect(vi.mocked(sendMessage).mock.calls[1]).toEqual(vi.mocked(sendMessage).mock.calls[0])
  await screen.findByRole('button', { name: '中断' })
})

it('recovers a cross-tab conflict without freezing or clearing the rejected draft', async () => {
  vi.mocked(sendMessage).mockRejectedValue(
    new ApiError(409, 'conversation_busy', '当前会话正在处理', 'conflict'),
  )
  const vault = createVault()
  view('first', vault)
  await screen.findByRole('button', { name: '发送' })
  type('保留内容')
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: running })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByRole('button', { name: '中断' })
  expect(vault.getSnapshot()['composer:first']).toMatchObject({
    text: '保留内容',
    pending: undefined,
  })
  expect(input().readOnly).toBe(false)
})

it('shares one SSE with the message card, blocks old retries and rejects a late running event after cancellation', async () => {
  history = [
    message({ ...running, id: 'old', targetId: 'older', state: 'failed' }),
    message(running),
  ]
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: running })
  vi.mocked(cancelJob).mockResolvedValue({ ...running, state: 'cancelled', fence: 3 })
  view()
  await screen.findByRole('button', { name: '中断' })
  await screen.findAllByText('原消息')
  await waitFor(() => expect(sources).toHaveLength(1))
  expect((screen.getByRole('button', { name: '重试' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(retryJob).not.toHaveBeenCalled()
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: null })
  fireEvent.click(screen.getByRole('button', { name: '中断' }))
  await screen.findByRole('button', { name: '发送' })
  act(() =>
    sources[0].dispatchEvent(
      new MessageEvent('snapshot', { data: JSON.stringify(feedback({ seq: 99 })) }),
    ),
  )
  expect(screen.queryByRole('button', { name: '中断' })).toBeNull()
  expect(screen.getAllByText('已中断').length).toBeGreaterThan(0)
})

it('keeps legacy queued work locked after the first task is interrupted', async () => {
  const next = { ...running, id: 'next', targetId: 'second', state: 'queued' as const }
  vi.mocked(readActiveAssistantJob)
    .mockResolvedValueOnce({ job: running })
    .mockResolvedValue({ job: next })
  vi.mocked(cancelJob).mockResolvedValue({ ...running, state: 'cancelled', fence: 3 })
  view()
  fireEvent.click(await screen.findByRole('button', { name: '中断' }))
  await waitFor(() =>
    expect((screen.getByRole('button', { name: '中断' }) as HTMLButtonElement).disabled).toBe(
      false,
    ),
  )
  expect(screen.queryByRole('button', { name: '发送' })).toBeNull()
})

it('ignores late restores after changing account and refreshes cross-tab activity signals', async () => {
  const previous = deferred<{ job: Job | null }>()
  vi.mocked(readActiveAssistantJob)
    .mockReturnValueOnce(previous.promise)
    .mockResolvedValue({ job: null })
  function Hook() {
    const task = useAssistantTask('first', [])
    return <span>{task.running ? task.job?.id : task.blocked ? 'checking' : 'idle'}</span>
  }
  const vault = createVault()
  const renderHook = (account: Identity) => (
    <TestWorkspace vault={vault} account={account}>
      <Hook />
    </TestWorkspace>
  )
  const mounted = render(renderHook(identity))
  const other = { ...identity, member: { ...identity.member, id: 'other' } }
  mounted.rerender(renderHook(other))
  await screen.findByText('idle')
  await act(async () => previous.resolve({ job: running }))
  expect(screen.queryByText('job')).toBeNull()
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: running })
  await act(async () =>
    window.dispatchEvent(
      new StorageEvent('storage', { key: 'paa-assistant-task:company:other:employee:first' }),
    ),
  )
  expect(screen.getByText('job')).toBeTruthy()
})

it('locks sending throughout an old-message retry, then registers the accepted execution', async () => {
  history = [message({ ...running, state: 'failed' })]
  const request = deferred<Job>()
  vi.mocked(retryJob).mockReturnValue(request.promise)
  view()
  const retry = await screen.findByRole('button', { name: '重试' })
  await waitFor(() => expect((retry as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(retry)
  type('下一条')
  fireEvent.keyDown(input(), { key: 'Enter' })
  expect(sendMessage).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '发送' })).toBeNull()
  const next = { ...running, state: 'queued' as const, attempt: 2, fence: 3 }
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: next })
  await act(async () => request.resolve(next))
  await screen.findByRole('button', { name: '中断' })
  expect(input().value).toBe('下一条')
})

it('does not replace a persisted terminal card with a stale active snapshot from the composer', () => {
  render(
    <TestWorkspace vault={createVault()}>
      <MemoryRouter>
        <MessageCard
          own
          message={message({ ...running, state: 'cancelled' })}
          activeJob={running}
          onChange={vi.fn()}
        />
      </MemoryRouter>
    </TestWorkspace>,
  )
  expect(screen.getByText('已中断')).toBeTruthy()
  expect(screen.queryByText('正在生成回复…')).toBeNull()
  expect(sources).toHaveLength(0)
})

it('adopts the newer context when another tab finishes a subsequent job before activity is observed', async () => {
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: running })
  vi.mocked(cancelJob).mockResolvedValue({ ...running, state: 'cancelled', fence: 3 })
  view()
  await screen.findByRole('button', { name: '中断' })
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: null })
  fireEvent.click(screen.getByRole('button', { name: '中断' }))
  await screen.findByRole('button', { name: '发送' })
  history = [
    message({
      ...running,
      id: 'newer',
      state: 'succeeded',
      updatedAt: '2026-09-02T01:00:00Z',
      contextUsage: {
        jobId: 'newer',
        attempt: 1,
        fence: 2,
        seq: 4,
        model: 'model',
        capacitySource: '测试容量',
        usedTokens: 300,
        contextWindow: 1000,
        inputLimit: 1000,
        outputReserve: 100,
        thresholdRatio: 0.9,
        estimated: true,
        state: 'ready',
        updatedAt: '2026-09-02T01:00:00Z',
      },
    }),
  ]
  await act(async () => window.dispatchEvent(new Event('online')))
  await screen.findByRole('button', { name: '上下文使用情况：约 30%' })
})
