// @vitest-environment jsdom
import type { Deliverable, DeliverableSummary } from '@paa/api-contracts'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DeliverableEntry } from '../../../apps/web/src/features/assistant/components/deliverables/Deliverable'
import { messageSubmission } from '../../../apps/web/src/features/assistant/utils/files'
import { Markdown } from '../../../apps/web/src/components/content/Markdown'
import { dialogs } from './helpers'

const summary: DeliverableSummary = {
  id: 'plan',
  revision: 2,
  latestRevision: 2,
  title: '客户实施计划',
  messageId: 'message',
  itemCount: 2,
  updatedAt: '2026-09-28T10:00:00Z',
}
const result: Deliverable = {
  ...summary,
  body: '范围和待确认问题',
  items: [
    { id: 'second', title: '接口联调', body: '按文档实现' },
    { id: 'first', title: '需求核对', body: '补充缺失资料' },
  ],
  links: [],
}
beforeEach(() => {
  dialogs()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(JSON.stringify({ ...result, revision: url.includes('revision=1') ? 1 : 2 }), {
          status: 200,
        }),
    ),
  )
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it.each(['继续修改', '加入我的工作'])(
  'returns focus to the composer after closing the panel: %s',
  async (action) => {
    const onContinue = vi.fn(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
      screen.getByRole('textbox', { name: '消息' }).focus()
    })
    render(
      <>
        <textarea aria-label="消息" />
        <DeliverableEntry item={summary} onContinue={onContinue} />
      </>,
    )
    const entry = screen.getByRole('button', { name: '查看客户实施计划' })
    entry.focus()
    fireEvent.click(entry)
    await screen.findByText('按文档实现')
    if (action === '加入我的工作') {
      fireEvent.click(screen.getByText('选择条目加入工作'))
      fireEvent.click(screen.getByRole('checkbox', { name: '1. 接口联调' }))
    }
    fireEvent.click(screen.getByRole('button', { name: action }))
    expect(onContinue).toHaveBeenCalledOnce()
    expect(document.activeElement).toBe(screen.getByRole('textbox', { name: '消息' }))
  },
)

it('keeps results collapsed until requested and sends exact selected IDs without creating work', async () => {
  const onContinue = vi.fn()
  render(<DeliverableEntry item={summary} onContinue={onContinue} />)
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查看客户实施计划' }))
  await screen.findByText('按文档实现')
  fireEvent.click(screen.getByText('选择条目加入工作'))
  fireEvent.click(screen.getByRole('checkbox', { name: '1. 接口联调' }))
  fireEvent.click(screen.getByRole('button', { name: '加入我的工作' }))
  expect(onContinue).toHaveBeenCalledWith(
    { id: 'plan', revision: 2, itemIds: ['second'] },
    '客户实施计划',
    '把《客户实施计划》第 1 项加入我的工作。',
  )
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(
    vi.mocked(fetch).mock.calls.every((call) => !call[1]?.method || call[1].method === 'GET'),
  ).toBe(true)
})

it('copies complete content, opens a precise historical version, and continues in chat', async () => {
  const onContinue = vi.fn()
  render(<DeliverableEntry item={summary} onContinue={onContinue} />)
  fireEvent.click(screen.getByRole('button', { name: '查看客户实施计划' }))
  await screen.findByText('按文档实现')
  fireEvent.click(screen.getByRole('button', { name: '复制' }))
  await screen.findByRole('button', { name: '已复制' })
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('2. 需求核对'))
  fireEvent.click(screen.getByText('版本 2'))
  fireEvent.click(screen.getByRole('button', { name: '上一版本' }))
  await screen.findByText('版本 1')
  fireEvent.click(screen.getByRole('button', { name: '继续修改' }))
  expect(onContinue).toHaveBeenCalledWith(
    { id: 'plan', revision: 1, itemIds: [] },
    '客户实施计划',
    undefined,
  )
})

it('clears inaccessible data and never exposes an action after a permission failure', async () => {
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify({ code: 'not_found', message: '记录不存在或无权查看' }), {
      status: 404,
    }),
  )
  render(<DeliverableEntry item={summary} onContinue={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: '查看客户实施计划' }))
  await screen.findByText('内容不存在或已不可访问。')
  expect(screen.queryByText('按文档实现')).toBeNull()
  expect(screen.queryByRole('button', { name: '继续修改' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '关闭' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('freezes the selected result inside the original idempotent send payload', () => {
  const reference = { id: 'plan', revision: 2, itemIds: ['first'] }
  const draft = { text: '继续改', files: [], key: 'send-key', deliverableReference: reference }
  const pending = messageSubmission(draft, 'conversation', 'professional')
  reference.itemIds.push('second')
  expect(pending.body.deliverableReference).toEqual({ id: 'plan', revision: 2, itemIds: ['first'] })
  expect(messageSubmission({ ...draft, text: '已变文字', pending }, 'other')).toBe(pending)
})

it('renders generated tables without interpreting HTML and keeps horizontal overflow local', () => {
  render(<Markdown text={'| 工作 | 下一步 |\n| --- | --- |\n| 方案 | <script>run()</script> |'} />)
  expect(screen.getByRole('table')).toBeTruthy()
  expect(screen.getAllByRole('columnheader')).toHaveLength(2)
  expect(document.querySelector('script')).toBeNull()
  expect(screen.getByText('<script>run()</script>')).toBeTruthy()
})
