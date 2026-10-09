// @vitest-environment jsdom
import type { Job, JobFeedback, ReplyStream, WorkMessage } from '@paa/api-contracts'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AssistantReply } from '../../../apps/web/src/features/assistant/components/messages/reply/AssistantReply'
import type { ComponentProps } from 'react'
import { replyPresentation } from '../../../apps/web/src/features/assistant/components/messages/reply/reply-presentation'
import { JobNotice } from '../../../apps/web/src/features/jobs/components/JobNotice'
import { useJobFeedback } from '../../../apps/web/src/hooks/useJobFeedback'

const job: Job = {
  id: 'stream-job',
  kind: 'message',
  targetId: 'message',
  state: 'running',
  attempt: 1,
  fence: 2,
  phase: 'assistant',
  error: '',
  updatedAt: '2026-10-01T00:00:00Z',
}
const stream = (
  text: string,
  generation = 1,
  state: ReplyStream['state'] = 'streaming',
): ReplyStream => ({
  version: 1,
  generation,
  state,
  text,
})
const message: WorkMessage = {
  id: 'message',
  ownerId: 'owner',
  conversationId: 'conversation',
  text: '提问',
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
const feedback = (text: string, seq = 1): JobFeedback => ({
  jobId: job.id,
  attempt: 1,
  fence: 2,
  seq,
  stage: 'generating',
  state: 'running',
  text: '',
  error: '',
  updatedAt: job.updatedAt,
  replyStream: stream(text),
})

function ReplyWithProgress(props: ComponentProps<typeof AssistantReply>) {
  const { message, job, feedback, own, unavailable } = props
  return (
    <>
      {job && (
        <JobNotice
          job={{ ...job, ...feedback }}
          refresh={vi.fn()}
          showNodes
          replyActivity={replyPresentation(message, job, feedback, own, unavailable).activity}
        />
      )}
      <AssistantReply {...props} />
    </>
  )
}

function animationFrames() {
  let time = 0
  let nextId = 0
  const pending = new Map<number, FrameRequestCallback>()
  vi.spyOn(performance, 'now').mockImplementation(() => time)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    pending.set(++nextId, callback)
    return nextId
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => pending.delete(id))
  return {
    pending,
    advance(milliseconds: number) {
      const until = time + milliseconds
      while (time < until) {
        time = Math.min(until, time + 16)
        const callbacks = [...pending.values()]
        pending.clear()
        act(() => callbacks.forEach((callback) => callback(time)))
      }
    },
  }
}
let frames: ReturnType<typeof animationFrames>
beforeEach(() => {
  frames = animationFrames()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('renders changing prefixes as safe Markdown without repeating prose or mounting final citations', () => {
  const view = render(
    <AssistantReply message={message} job={job} feedback={feedback('# 标题\n\n第一段')} own />,
  )
  expect(screen.getByRole('heading', { name: '标题' })).toBeTruthy()
  view.rerender(
    <AssistantReply
      message={message}
      job={job}
      feedback={feedback(
        '# 标题\n\n第一段完整😀\n```json\n{"key":"value"}\n<script>alert(1)</script>',
        2,
      )}
      own
    />,
  )
  frames.advance(480)
  expect(screen.getAllByText('第一段完整😀')).toHaveLength(1)
  expect(view.container.querySelector('pre code')).toBeTruthy()
  expect(view.container.querySelector('script')).toBeNull()
  expect(view.container.querySelector('button')).toBeNull()
})

it('retains preview through terminal feedback and only replaces it with a persisted result of the same attempt', () => {
  const terminal = {
    ...feedback('未完成前缀'),
    state: 'awaiting_input' as const,
    replyStream: stream('未完成前缀', 1, 'finalizing'),
  }
  const view = render(
    <ReplyWithProgress
      message={message}
      job={{ ...job, state: 'awaiting_input' }}
      feedback={terminal}
      own
    />,
  )
  expect(screen.getByText('未完成前缀')).toBeTruthy()
  expect(screen.getByRole('status').textContent).toBe('核对并保存回复 · 处理中')
  expect(view.container.querySelector('[data-reply-state] [role="status"]')).toBeNull()
  // An old message returned from a cache must not win during the final GET.
  view.rerender(
    <ReplyWithProgress
      message={{
        ...message,
        reply: '旧答复',
        job: { ...job, attempt: 0, state: 'awaiting_input' },
      }}
      job={job}
      feedback={terminal}
      own
    />,
  )
  expect(screen.queryByText('旧答复')).toBeNull()
  expect(screen.getByText('未完成前缀')).toBeTruthy()
  view.rerender(
    <ReplyWithProgress
      message={{ ...message, reply: '**正式答复**', job: { ...job, state: 'awaiting_input' } }}
      job={job}
      feedback={terminal}
      own
    />,
  )
  expect(screen.getByText('正式答复').tagName).toBe('STRONG')
  expect(screen.queryByText('未完成前缀')).toBeNull()
  expect(screen.queryByText('核对并保存回复 · 处理中')).toBeNull()
})

it('restores interrupted prefix from message DTO and labels cancellation without showing success', () => {
  const cancelled = { ...job, fence: 3, state: 'cancelled' as const }
  render(
    <ReplyWithProgress
      message={{ ...message, job: cancelled, replyStream: stream('已生成片段', 1, 'interrupted') }}
      job={cancelled}
      feedback={null}
      own
    />,
  )
  expect(screen.getByText('已生成片段')).toBeTruthy()
  expect(screen.getByText('已中断')).toBeTruthy()
})

it('clears retry, withdrawn, unavailable and foreign-account previews', () => {
  const restored = { ...message, replyStream: stream('旧片段') }
  const view = render(<ReplyWithProgress message={restored} job={job} feedback={null} own />)
  expect(screen.getByText('旧片段')).toBeTruthy()
  expect(screen.getByRole('status').textContent).toBe('生成回答 · 处理中')
  view.rerender(
    <ReplyWithProgress message={restored} job={{ ...job, attempt: 2 }} feedback={null} own />,
  )
  expect(screen.queryByText('旧片段')).toBeNull()
  expect(screen.queryByText('生成回答 · 处理中')).toBeNull()
  view.rerender(
    <ReplyWithProgress
      message={restored}
      job={job}
      feedback={{ ...feedback(''), replyStream: stream('', 2, 'withdrawn') }}
      own
    />,
  )
  expect(screen.queryByText('旧片段')).toBeNull()
  expect(screen.queryByText('生成回答 · 处理中')).toBeNull()
  view.rerender(<ReplyWithProgress message={restored} job={job} feedback={null} own unavailable />)
  expect(screen.queryByText('旧片段')).toBeNull()
  expect(screen.queryByText('生成回答 · 处理中')).toBeNull()
  view.rerender(<ReplyWithProgress message={restored} job={job} feedback={null} own={false} />)
  expect(screen.queryByText('旧片段')).toBeNull()
  expect(screen.queryByText('生成回答 · 处理中')).toBeNull()
})

it('shares one connection, adds no request per prefix, and withdraws DTO fallback on access loss', () => {
  const sources: Source[] = []
  class Source extends EventTarget {
    close = vi.fn()
    constructor() {
      super()
      sources.push(this)
    }
  }
  vi.stubGlobal('EventSource', Source)
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const refresh = vi.fn()
  function Consumer({ reply = false }: { reply?: boolean }) {
    const live = useJobFeedback(job, true, refresh)
    return reply ? (
      <AssistantReply
        message={{ ...message, replyStream: stream('DTO片段') }}
        job={job}
        feedback={live.feedback}
        unavailable={live.unavailable}
        own
      />
    ) : null
  }
  render(
    <>
      <Consumer reply />
      <Consumer />
    </>,
  )
  expect(sources).toHaveLength(1)
  for (let i = 1; i <= 8; i++)
    act(() =>
      sources[0].dispatchEvent(
        new MessageEvent('snapshot', { data: JSON.stringify(feedback('前缀' + i, i)) }),
      ),
    )
  expect(screen.getByText('前缀8')).toBeTruthy()
  expect(fetch).not.toHaveBeenCalled()
  expect(refresh).not.toHaveBeenCalled()
  act(() =>
    sources[0].dispatchEvent(
      new MessageEvent('unavailable', { data: JSON.stringify({ status: 403 }) }),
    ),
  )
  expect(screen.queryByText('前缀8')).toBeNull()
  expect(screen.queryByText('DTO片段')).toBeNull()
  expect(sources[0].close).toHaveBeenCalledTimes(1)
})

it('shows the server-sealed cancellation response while final message GET is delayed or fails', () => {
  const sealed = {
    ...job,
    state: 'cancelled' as const,
    fence: 3,
    replyStream: stream('中断前最后一段', 1, 'interrupted'),
  }
  // The POST has advanced the fence and closed SSE, while history still carries
  // the running execution. Only the POST's authorized snapshot may bridge it.
  const view = render(<ReplyWithProgress message={message} job={sealed} feedback={null} own />)
  expect(screen.getByText('中断前最后一段')).toBeTruthy()
  expect(screen.getByText('已中断')).toBeTruthy()
  view.rerender(
    <ReplyWithProgress
      message={{ ...message, job: sealed, replyStream: sealed.replyStream }}
      job={sealed}
      feedback={null}
      own
    />,
  )
  expect(screen.getAllByText('中断前最后一段')).toHaveLength(1)
  view.rerender(
    <ReplyWithProgress message={message} job={sealed} feedback={null} own unavailable />,
  )
  expect(screen.queryByText('中断前最后一段')).toBeNull()
})

it('smooths fresh prefixes across frames and catches up with bursts within 500ms', () => {
  const view = render(<AssistantReply message={message} job={job} feedback={null} own />)
  const text = '这是一段正在生成的回复。'.repeat(20)
  view.rerender(<AssistantReply message={message} job={job} feedback={feedback(text)} own />)
  const visible = () => view.container.querySelector('p')?.textContent ?? ''
  const lengths: number[] = []
  for (let i = 0; i < 6; i++) {
    frames.advance(64)
    const value = visible()
    expect(text.startsWith(value)).toBe(true)
    expect(value.length).toBeGreaterThan(lengths.at(-1) ?? 0)
    expect(value.length).toBeLessThan(text.length)
    lengths.push(value.length)
  }
  frames.advance(116)
  expect(visible()).toBe(text)
  expect(frames.pending.size).toBe(0)

  const longer = text + '大量后续内容。'.repeat(300)
  view.rerender(<AssistantReply message={message} job={job} feedback={feedback(longer, 2)} own />)
  expect(visible()).toBe(text)
  frames.advance(64)
  expect(visible().length).toBeGreaterThan(text.length)
  expect(visible().length).toBeLessThan(longer.length)
  frames.advance(436)
  expect(visible()).toBe(longer)
  expect(frames.pending.size).toBe(0)
})

it('restores existing text immediately and only animates later live additions', () => {
  const restored = { ...message, replyStream: stream('已恢复的正文') }
  const view = render(<AssistantReply message={restored} job={job} feedback={null} own />)
  expect(screen.getByText('已恢复的正文')).toBeTruthy()
  view.rerender(
    <AssistantReply message={restored} job={job} feedback={feedback('已恢复的正文')} own />,
  )
  expect(frames.pending.size).toBe(0)
  const text = '已恢复的正文' + '随后实时生成的文字'.repeat(20)
  view.rerender(<AssistantReply message={restored} job={job} feedback={feedback(text, 2)} own />)
  expect(screen.getByText('已恢复的正文')).toBeTruthy()
  frames.advance(80)
  const partial = view.container.querySelector('p')!.textContent!
  expect(partial.startsWith('已恢复的正文')).toBe(true)
  expect(partial.length).toBeGreaterThan('已恢复的正文'.length)
  expect(partial.length).toBeLessThan(text.length)
  frames.advance(420)
  expect(screen.getByText(text)).toBeTruthy()
})

it('keeps every animation frame on Unicode grapheme boundaries, including across snapshots', () => {
  const initial = '开始a'
  const view = render(
    <AssistantReply message={message} job={job} feedback={feedback(initial)} own />,
  )
  const text = initial + '\u0301👨‍👩‍👧‍👦👍🏽🇨🇳e\u0301结束'.repeat(10)
  const boundaries = new Set([0])
  for (const part of new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text))
    boundaries.add(part.index + part.segment.length)
  view.rerender(<AssistantReply message={message} job={job} feedback={feedback(text, 2)} own />)
  const visible = () => view.container.querySelector('p')!.textContent!
  // The accent extending the previous final grapheme is shown with its base.
  expect(visible()).toBe('开始a\u0301')
  for (let i = 0; i < 32; i++) {
    frames.advance(16)
    expect(text.startsWith(visible())).toBe(true)
    expect(boundaries.has(visible().length)).toBe(true)
  }
  expect(visible()).toBe(text)
})

it.each(['finalizing', 'interrupted', 'cancelled', 'persisted'] as const)(
  'settles pending text immediately on %s without a typing tail',
  (ending) => {
    const view = render(
      <AssistantReply message={message} job={job} feedback={feedback('开头')} own />,
    )
    const text = '开头' + '尚在显示队列中的文字'.repeat(20)
    view.rerender(<AssistantReply message={message} job={job} feedback={feedback(text, 2)} own />)
    frames.advance(48)
    expect(view.container.querySelector('p')!.textContent!.length).toBeLessThan(text.length)
    const state =
      ending === 'cancelled' ? 'cancelled' : ending === 'persisted' ? 'awaiting_input' : 'running'
    const finalFeedback: JobFeedback = {
      ...feedback(text, 3),
      state,
      replyStream: stream(text, 1, ending === 'finalizing' ? 'finalizing' : 'interrupted'),
    }
    view.rerender(
      <AssistantReply
        message={
          ending === 'persisted'
            ? { ...message, reply: '正式结果', job: { ...job, state: 'awaiting_input' } }
            : message
        }
        job={job}
        feedback={finalFeedback}
        own
      />,
    )
    expect(screen.getByText(ending === 'persisted' ? '正式结果' : text)).toBeTruthy()
    expect(frames.pending.size).toBe(0)
    frames.advance(600)
    expect(screen.getByText(ending === 'persisted' ? '正式结果' : text)).toBeTruthy()
  },
)

it.each(['message', 'job', 'attempt', 'fence', 'generation'] as const)(
  'discards queued characters when %s identity changes',
  (field) => {
    const view = render(
      <AssistantReply message={message} job={job} feedback={feedback('旧')} own />,
    )
    view.rerender(
      <AssistantReply message={message} job={job} feedback={feedback('旧'.repeat(200), 2)} own />,
    )
    frames.advance(32)
    const nextJob = {
      ...job,
      id: field === 'job' ? 'new-job' : job.id,
      attempt: field === 'attempt' ? 2 : job.attempt,
      fence: field === 'fence' ? 3 : job.fence,
    }
    const text = '新'.repeat(200)
    view.rerender(
      <AssistantReply
        message={field === 'message' ? { ...message, id: 'new-message' } : message}
        job={nextJob}
        feedback={{
          ...feedback(text, 3),
          jobId: nextJob.id,
          attempt: nextJob.attempt!,
          fence: nextJob.fence!,
          replyStream: stream(text, field === 'generation' ? 2 : 1),
        }}
        own
      />,
    )
    expect(view.container.textContent).not.toContain('旧')
    frames.advance(500)
    expect(screen.getByText(text)).toBeTruthy()
    expect(view.container.textContent).not.toContain('旧')
  },
)

it.each(['withdrawn', 'unavailable', 'foreign', 'business', 'unmount'] as const)(
  'cancels queued animation immediately on %s',
  (ending) => {
    const view = render(
      <AssistantReply message={message} job={job} feedback={feedback('旧')} own />,
    )
    view.rerender(
      <AssistantReply message={message} job={job} feedback={feedback('旧'.repeat(200), 2)} own />,
    )
    frames.advance(32)
    expect(frames.pending.size).toBe(1)
    if (ending === 'unmount') view.unmount()
    else
      view.rerender(
        <AssistantReply
          message={ending === 'business' ? { ...message, businessUnavailable: true } : message}
          job={job}
          feedback={{
            ...feedback('旧'.repeat(200), 3),
            ...(ending === 'withdrawn' ? { replyStream: stream('', 2, 'withdrawn') } : {}),
          }}
          own={ending !== 'foreign'}
          unavailable={ending === 'unavailable'}
        />,
      )
    expect(view.container.textContent).toBe('')
    expect(frames.pending.size).toBe(0)
    frames.advance(600)
    expect(view.container.textContent).toBe('')
  },
)

it('replaces a corrected prefix immediately even without a generation change', () => {
  const view = render(
    <AssistantReply message={message} job={job} feedback={feedback('旧候选')} own />,
  )
  view.rerender(
    <AssistantReply message={message} job={job} feedback={feedback('旧候选'.repeat(100), 2)} own />,
  )
  frames.advance(48)
  view.rerender(<AssistantReply message={message} job={job} feedback={feedback('已修正', 3)} own />)
  expect(screen.getByText('已修正')).toBeTruthy()
  expect(frames.pending.size).toBe(0)
  frames.advance(600)
  expect(screen.queryByText(/旧候选/)).toBeNull()
})

it('bypasses smoothing for reduced motion and settles when the preference changes', () => {
  const query = Object.assign(new EventTarget(), { matches: true })
  vi.stubGlobal('matchMedia', () => query)
  const view = render(<AssistantReply message={message} job={job} feedback={null} own />)
  const first = '直接展示'
  view.rerender(<AssistantReply message={message} job={job} feedback={feedback(first)} own />)
  expect(screen.getByText(first)).toBeTruthy()
  expect(frames.pending.size).toBe(0)
  act(() => {
    query.matches = false
    query.dispatchEvent(new Event('change'))
  })
  const text = first + '后续逐步展示'.repeat(30)
  view.rerender(<AssistantReply message={message} job={job} feedback={feedback(text, 2)} own />)
  frames.advance(32)
  expect(view.container.querySelector('p')!.textContent!.length).toBeLessThan(text.length)
  act(() => {
    query.matches = true
    query.dispatchEvent(new Event('change'))
  })
  expect(screen.getByText(text)).toBeTruthy()
  expect(frames.pending.size).toBe(0)
})
