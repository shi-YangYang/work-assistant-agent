// @vitest-environment jsdom
import type { Conversation, Job, WorkMessage } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Breadcrumbs } from '../../../apps/web/src/app/layout/Breadcrumbs'
import { Assistant } from '../../../apps/web/src/features/assistant/components/conversation/Conversations'
import { assistantQuery } from '../../../apps/web/src/features/assistant/api/queries'
import { createVault, deferred, dialogs, TestWorkspace } from './helpers'

const conversation = {
  id: 'chat',
  title: '项目计划',
  revision: 1,
  personaId: 'professional',
  executionMode: 'auto',
  fullAccessConfirmed: false,
} as Conversation
const running = {
  id: 'job',
  targetId: 'message',
  kind: 'message',
  state: 'running',
  phase: 'assistant',
  attempt: 1,
  fence: 1,
  stage: 'generating',
  updatedAt: '2026-09-01',
  error: '',
} as Job
let active: Job | null
let messages: WorkMessage[]
let delayMessages: Promise<Response> | undefined
const counts = () => {
  const result: Record<string, number> = {}
  for (const [url] of vi.mocked(fetch).mock.calls)
    result[String(url)] = (result[String(url)] ?? 0) + 1
  return result
}
const six = [
  '/conversations/chat',
  '/messages?conversationId=chat',
  '/business-actions?conversationId=chat&orphanOnly=true',
  '/conversations/chat/active-job',
  '/conversations/chat/interactions',
  '/conversations/chat/context-usage',
].map((path) => '/api/v1' + path)
const sources: Source[] = []
class Source extends EventTarget {
  close = vi.fn()
  onerror?: () => void
  constructor() {
    super()
    sources.push(this)
  }
}
function Page() {
  const { id } = useParams()
  return (
    <>
      <Breadcrumbs />
      <Assistant conversationId={id} />
    </>
  )
}
function view(route = '/assistant/chat') {
  return render(
    <StrictMode>
      <TestWorkspace vault={createVault()}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path="/assistant/:id?" element={<Page />} />
          </Routes>
        </MemoryRouter>
      </TestWorkspace>
    </StrictMode>,
  )
}
beforeEach(() => {
  dialogs()
  sources.length = 0
  active = null
  messages = []
  delayMessages = undefined
  vi.stubGlobal('EventSource', Source)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL) => {
      const path = String(url).replace('/api/v1', '')
      if (path.startsWith('/messages?') && delayMessages) return delayMessages
      const data =
        path === '/conversations/chat'
          ? conversation
          : path.endsWith('/active-job')
            ? { job: active }
            : path.endsWith('/context-usage')
              ? { contextUsage: null }
              : path.startsWith('/messages?')
                ? { items: messages, nextCursor: null }
                : { items: [], nextCursor: null }
      return new Response(JSON.stringify(data))
    }),
  )
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
async function ready() {
  await screen.findByRole('button', { name: '发送' })
  await waitFor(() => expect(Object.keys(counts())).toHaveLength(6))
}

it('shares six initial resources between breadcrumbs and StrictMode-mounted assistant and stays idle', async () => {
  view()
  await ready()
  expect(counts()).toEqual(Object.fromEntries(six.map((path) => [path, 1])))
  vi.useFakeTimers()
  await act(async () => {
    for (let index = 0; index < 10; index++) window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(60000)
  })
  expect(counts()).toEqual(Object.fromEntries(six.map((path) => [path, 1])))
})

it('merges online, visibility and repeated focus events including neighboring event-loop turns', async () => {
  view()
  await ready()
  await act(async () => {
    window.dispatchEvent(new Event('online'))
    await Promise.resolve()
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('focus'))
  })
  await waitFor(() => expect(counts()[six[1]]).toBe(2))
  expect(counts()).toEqual(Object.fromEntries(six.map((path) => [path, 2])))
})

it.each([
  ['/assistant', '/api/v1/conversations'],
  ['/assistant?workId=work', '/api/v1/conversations?order=last_message'],
])('retries a failed restore from %s only when the user asks', async (route, restorePath) => {
  const normal = vi.mocked(fetch).getMockImplementation()!
  let available = false
  vi.mocked(fetch).mockImplementation(async (...args) => {
    if (String(args[0]) === restorePath)
      return available
        ? new Response(JSON.stringify({ items: [conversation], nextCursor: null }))
        : new Response('{}', { status: 503 })
    if (String(args[0]) === '/api/v1/works/work')
      return new Response(JSON.stringify({ id: 'work', ownerId: 'owner', title: '待引用工作' }))
    return normal(...args)
  })
  view(route)
  await screen.findByText('服务暂时不可用，请稍后重试。')
  expect(counts()[restorePath]).toBe(1)
  available = true
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await screen.findByRole('heading', { name: conversation.title })
  await screen.findByRole('button', { name: '发送' })
  expect(counts()[restorePath]).toBe(2)
  expect(counts()[six[0]]).toBe(1)
})

it.each(['online', 'manual'] as const)(
  'recovers a failed detail via %s before the chat is mounted',
  async (recovery) => {
    const normal = vi.mocked(fetch).getMockImplementation()!
    let available = false
    vi.mocked(fetch).mockImplementation(async (...args) => {
      if (String(args[0]) === six[0] && !available) return new Response('{}', { status: 503 })
      return normal(...args)
    })
    view()
    await screen.findByText('服务暂时不可用，请稍后重试。')
    expect(counts()).toEqual({ [six[0]]: 1 })
    expect(screen.queryByRole('button', { name: '发送' })).toBeNull()
    available = true
    vi.spyOn(Date, 'now').mockReturnValue(Date.now())
    if (recovery === 'manual') fireEvent.click(screen.getByRole('button', { name: '重试' }))
    else
      await act(async () => {
        window.dispatchEvent(new Event('online'))
      })
    await ready()
    if (recovery === 'online') {
      // The coordinator keeps its merge window when detail recovery mounts the chat.
      await act(async () => {
        document.dispatchEvent(new Event('visibilitychange'))
      })
    }
    expect(counts()).toEqual(Object.fromEntries(six.map((path, index) => [path, index ? 1 : 2])))
  },
)

it('does not read conversation resources or hidden pickers before a new conversation exists', async () => {
  view('/assistant?new=1')
  await screen.findByRole('button', { name: '发送' })
  expect(fetch).not.toHaveBeenCalled()
  fireEvent.change(screen.getByRole('textbox', { name: '工作消息' }), {
    target: { value: '只编辑草稿' },
  })
  await act(async () => {
    window.dispatchEvent(new Event('online'))
    document.dispatchEvent(new Event('visibilitychange'))
  })
  expect(fetch).not.toHaveBeenCalled()
})

it('updates heading and breadcrumb from a complete saved conversation without refetching chat resources', async () => {
  view()
  await ready()
  const query = assistantQuery<Conversation>('/conversations/chat', 'company:owner:employee')!
  act(() => query.set({ ...conversation, title: '修改后的标题', revision: 2 }))
  await screen.findByRole('heading', { name: '修改后的标题' })
  expect(screen.getByText('修改后的标题', { selector: 'strong' })).toBeTruthy()
  expect(counts()).toEqual(Object.fromEntries(six.map((path) => [path, 1])))
})

it('uses one shared SSE and reconciles one final result even when both consumers observe completion', async () => {
  active = running
  messages = [
    {
      id: 'message',
      ownerId: 'owner',
      conversationId: 'chat',
      text: '查询公开资料',
      reply: '',
      createdAt: '2026-09-01',
      attachments: [],
      drafts: [],
      suggestions: [],
      job: running,
    } as unknown as WorkMessage,
  ]
  view()
  await screen.findByRole('button', { name: '中断' })
  await waitFor(() => expect(sources).toHaveLength(1))
  await screen.findByText('查询公开资料')
  expect(counts()).toEqual(Object.fromEntries(six.map((path) => [path, 1])))
  messages = [
    { ...messages[0], reply: '已整理三项公开资料', job: { ...running, state: 'succeeded' } },
  ]
  active = null
  await act(async () =>
    sources[0].dispatchEvent(
      new MessageEvent('snapshot', {
        data: JSON.stringify({
          jobId: 'job',
          attempt: 1,
          fence: 1,
          seq: 2,
          state: 'succeeded',
          stage: 'complete',
          text: '',
          error: '',
          updatedAt: '2026-09-02',
        }),
      }),
    ),
  )
  await screen.findByText('已整理三项公开资料')
  await screen.findByRole('button', { name: '发送' })
  expect(counts()[six[1]]).toBe(2)
  expect(counts()[six[2]]).toBe(2)
  expect(counts()[six[3]]).toBe(2)
  expect(counts()[six[4]]).toBe(2)
  expect(counts()[six[0]]).toBe(1)
  expect(counts()[six[5]]).toBe(1)
  expect(sources).toHaveLength(1)
})

it('does not lose the completed reply when completion overtakes a slow earlier history refresh', async () => {
  active = running
  view()
  await screen.findByRole('button', { name: '中断' })
  const stale = deferred<Response>()
  delayMessages = stale.promise
  await act(async () => window.dispatchEvent(new Event('online')))
  await waitFor(() => expect(counts()[six[1]]).toBe(2))
  messages = [
    {
      id: 'message',
      ownerId: 'owner',
      conversationId: 'chat',
      text: '原消息',
      reply: '最终完整结果',
      createdAt: '2026-09-01',
      attachments: [],
      drafts: [],
      suggestions: [],
      job: { ...running, state: 'succeeded' },
    } as unknown as WorkMessage,
  ]
  active = null
  delayMessages = undefined
  await act(async () => {
    sources[0].dispatchEvent(
      new MessageEvent('snapshot', {
        data: JSON.stringify({
          jobId: 'job',
          attempt: 1,
          fence: 1,
          seq: 2,
          state: 'succeeded',
          stage: 'complete',
          text: '',
          error: '',
          updatedAt: '2026-09-02',
        }),
      }),
    )
    stale.resolve(new Response(JSON.stringify({ items: [], nextCursor: null })))
  })
  await screen.findByText('最终完整结果')
  expect(counts()[six[1]]).toBe(3)
})

it('uses streamed thinking, search, operation and review changes without refetching persisted records', async () => {
  active = running
  view()
  await screen.findByRole('button', { name: '中断' })
  await waitFor(() => expect(Object.keys(counts())).toHaveLength(6))
  await act(async () => {
    for (const [seq, stage] of [
      'generating',
      'searching',
      'generating',
      'operating',
      'reviewing',
    ].entries())
      sources[0].dispatchEvent(
        new MessageEvent('snapshot', {
          data: JSON.stringify({
            jobId: 'job',
            attempt: 1,
            fence: 1,
            seq,
            state: 'running',
            stage,
            text: `片段${seq}`,
            error: '',
            updatedAt: `2026-09-0${seq + 1}`,
          }),
        }),
      )
  })
  expect(counts()).toEqual(Object.fromEntries(six.map((path) => [path, 1])))
  await act(async () => {
    for (const [index, stage] of ['transcribing', 'generating'].entries())
      sources[0].dispatchEvent(
        new MessageEvent('snapshot', {
          data: JSON.stringify({
            jobId: 'job',
            attempt: 1,
            fence: 1,
            seq: 8 + index,
            state: 'running',
            stage,
            text: '',
            error: '',
            updatedAt: '2026-09-09',
          }),
        }),
      )
  })
  await waitFor(() => expect(counts()[six[1]]).toBe(2))
  expect(Object.keys(counts()).filter((path) => counts()[path] === 2)).toEqual([six[1]])
})
