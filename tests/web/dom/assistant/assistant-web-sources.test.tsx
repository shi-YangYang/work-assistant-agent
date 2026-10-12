// @vitest-environment jsdom
import type { Job, WebReadSource, WorkMessage } from '@paa/api-contracts'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { AssistantReply } from '../../../../apps/web/src/features/assistant/components/messages/reply/AssistantReply'
import { WebSources } from '../../../../apps/web/src/features/assistant/components/messages/reply/WebSources'

afterEach(cleanup)

const sources: WebReadSource[] = [
  { url: 'https://publisher.example/one', title: '第一篇原文', refetchFailed: false },
  { url: 'https://publisher.example/two', title: '第二篇原文', refetchFailed: true },
]
const job: Job = {
  id: 'read-job',
  kind: 'message',
  targetId: 'message',
  state: 'succeeded',
  attempt: 1,
  fence: 1,
  phase: 'complete',
  error: '',
  updatedAt: '2026-10-08T00:00:00Z',
}
const message: WorkMessage = {
  id: 'message',
  ownerId: 'owner',
  conversationId: 'conversation',
  text: '整理网页',
  reply: '整理后的正文，没有手写来源链接。',
  replyTo: null,
  transcript: '',
  transcriptRevision: 0,
  createdAt: job.updatedAt,
  attachments: [],
  drafts: [],
  suggestions: [],
  webSources: sources,
  job,
}

it('renders persisted page sources after delivery even when prose has no links', () => {
  const view = render(<AssistantReply message={message} job={job} feedback={null} own />)
  expect(screen.getByText(message.reply)).toBeTruthy()
  const summary = screen.getByText('本轮读取的网页 · 2')
  const details = summary.closest('details')!
  expect(details.open).toBe(false)
  fireEvent.click(summary)
  expect(details.open).toBe(true)
  expect(screen.getByRole('link', { name: /第一篇原文/ }).getAttribute('href')).toBe(sources[0].url)
  const second = screen.getByRole('link', { name: /第二篇原文/ })
  expect(second.textContent).toContain('后续读取未成功')
  expect(second.getAttribute('target')).toBe('_blank')
  expect(second.getAttribute('rel')).toBe('noreferrer noopener')
  expect(screen.getByText(/不代表逐条核实了答复/)).toBeTruthy()
  view.rerender(
    <AssistantReply message={{ ...message, webSources: [] }} job={job} feedback={null} own />,
  )
  expect(view.container.querySelector('details')).toBeNull()
  expect(screen.getByText(message.reply)).toBeTruthy()
})

it.each(['running', 'failed', 'awaiting_retry', 'cancelled'] as const)(
  'does not mount final page sources during %s',
  (state) => {
    const pending = {
      ...job,
      state,
      replyStream: {
        version: 1 as const,
        generation: 1,
        state: 'streaming' as const,
        text: '候选正文',
      },
    }
    const view = render(
      <AssistantReply message={{ ...message, job: pending }} job={pending} feedback={null} own />,
    )
    expect(view.container.querySelector('details')).toBeNull()
    expect(view.container.querySelector('a')).toBeNull()
  },
)

it('hides all sources when message access becomes unavailable', () => {
  const view = render(
    <AssistantReply
      message={{ ...message, businessUnavailable: true }}
      job={job}
      feedback={null}
      own
    />,
  )
  expect(view.container.textContent).toBe('')
})

it('deduplicates URLs, rejects unsafe link schemes and renders bounded literal titles', () => {
  const title = '<script>alert(1)</script>' + '超长报道标题'.repeat(100)
  const rows = [
    { ...sources[0], title },
    { ...sources[0], url: sources[0].url + '#fragment', title: '同一原文' },
    { ...sources[1], url: 'javascript:alert(1)' },
    { ...sources[1], url: 'data:text/html,hello' },
    { ...sources[1], url: 'https://name:password@publisher.example/' },
    { ...sources[1], url: 'https://publisher.example/\nattack' },
  ]
  const view = render(<WebSources sources={rows} />)
  expect(screen.getByText('本轮读取的网页 · 1')).toBeTruthy()
  expect(view.container.querySelectorAll('a')).toHaveLength(1)
  expect(view.container.querySelector('script')).toBeNull()
  expect(view.container.querySelector('a > span')!.textContent).toBe(title.slice(0, 200))
  expect(screen.queryByText('同一原文')).toBeNull()
})
