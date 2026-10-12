// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Job } from '@paa/api-contracts'
import { useAssistantActivity } from '../../../../apps/web/src/hooks/useAssistantActivity'
import { useJobFeedback } from '../../../../apps/web/src/hooks/useJobFeedback'
import {
  AssistantActivityStore,
  mountAssistantActivity,
} from '../../../../apps/web/src/api/assistant-activity'
import { setCsrf } from '../../../../apps/web/src/api/client'
import { deferred } from '../helpers'

const sources: Source[] = []
class Source extends EventTarget {
  close = vi.fn()
  constructor(readonly url: string) {
    super()
    sources.push(this)
  }
}
const jobs = [
  {
    id: 'current',
    conversationId: 'conversation',
    targetId: 'message',
    state: 'running',
    stage: 'generating',
    attempt: 1,
    fence: 1,
    seq: 1,
    updatedAt: '2026-10-12',
  },
]
function MessageObserver({ job }: { job: Job }) {
  useJobFeedback(job, true, () => {})
  return <span>{job.state}</span>
}
function ShellObserver({
  owner = 'first',
  page = 'assistant',
  messageJob,
}: {
  owner?: string
  page?: string
  messageJob?: Job
}) {
  const activity = useAssistantActivity(owner)
  return (
    <>
      <output aria-label="活动状态">{activity}</output>
      <main>{page}</main>
      {page === 'assistant' && messageJob && <MessageObserver job={messageJob} />}
    </>
  )
}
beforeEach(() => {
  sources.length = 0
  setCsrf('session')
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  vi.stubGlobal('EventSource', Source)
})
afterEach(() => {
  cleanup()
  setCsrf('')
  vi.unstubAllGlobals()
})
it('recovers a delayed cold snapshot under StrictMode and keeps the subscription across pages', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url: string, options?: RequestInit) =>
        new Promise<Response>((resolve, reject) => {
          const timer = setTimeout(() => resolve(new Response(JSON.stringify({ jobs }))), 10)
          options?.signal?.addEventListener('abort', () => {
            clearTimeout(timer)
            reject(new DOMException('aborted', 'AbortError'))
          })
        }),
    ),
  )
  const view = render(
    <StrictMode>
      <ShellObserver />
    </StrictMode>,
  )
  expect(screen.getByLabelText('活动状态').textContent).toBe('idle')
  await waitFor(() => expect(screen.getByLabelText('活动状态').textContent).toBe('working'))
  expect(sources).toHaveLength(1)
  const count = vi.mocked(fetch).mock.calls.length
  view.rerender(
    <StrictMode>
      <ShellObserver page="work" />
    </StrictMode>,
  )
  expect(screen.getByLabelText('活动状态').textContent).toBe('working')
  expect(vi.mocked(fetch).mock.calls).toHaveLength(count)
  expect(sources).toHaveLength(1)
  view.unmount()
  await act(async () => {})
  expect(sources[0].close).toHaveBeenCalledTimes(1)
})
it('clears activity when returning chat history confirms completion before the terminal event', async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify({ jobs })))
  vi.stubGlobal('fetch', fetch)
  const running: Job = {
    id: jobs[0].id,
    targetId: jobs[0].targetId,
    kind: 'message',
    state: 'running',
    phase: 'assistant',
    stage: 'generating',
    attempt: 1,
    fence: 1,
    updatedAt: jobs[0].updatedAt,
    error: '',
  }
  const view = render(<ShellObserver messageJob={running} />)
  await waitFor(() => expect(screen.getByLabelText('活动状态').textContent).toBe('working'))
  expect(sources).toHaveLength(1)
  view.rerender(<ShellObserver page="work" />)
  expect(screen.getByLabelText('活动状态').textContent).toBe('working')
  // The persisted reply can arrive before the final SSE snapshot after navigation.
  view.rerender(
    <ShellObserver
      messageJob={{
        ...running,
        state: 'succeeded',
        stage: 'complete',
        updatedAt: '2026-10-12T00:01:00Z',
      }}
    />,
  )
  await waitFor(() => expect(screen.getByLabelText('活动状态').textContent).toBe('idle'))
  expect(sources[0].close).toHaveBeenCalledTimes(1)
  expect(fetch).toHaveBeenCalledTimes(1)
})
it('restarts discovery after cleanup even when the aborted request settles later', async () => {
  const first = deferred<Response>()
  const fetch = vi
    .fn()
    .mockImplementationOnce(() => first.promise)
    .mockResolvedValue(new Response(JSON.stringify({ jobs })))
  vi.stubGlobal('fetch', fetch)
  const store = new AssistantActivityStore('strict')
  const dispose = mountAssistantActivity(store)
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  dispose()
  const again = mountAssistantActivity(store)
  try {
    await act(async () => first.resolve(new Response(JSON.stringify({ jobs: [] }))))
    await waitFor(() => expect(store.getSnapshot()).toBe('working'))
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(sources).toHaveLength(1)
  } finally {
    again()
  }
})
it('does not revive the old account when a snapshot finishes after identity replacement', async () => {
  const first = deferred<Response>()
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValue(new Response(JSON.stringify({ jobs: [] }))),
  )
  const view = render(<ShellObserver />)
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  setCsrf('new-session')
  view.rerender(<ShellObserver owner="second" />)
  await act(async () => first.resolve(new Response(JSON.stringify({ jobs }))))
  expect(screen.getByLabelText('活动状态').textContent).toBe('idle')
  expect(sources).toHaveLength(0)
})
