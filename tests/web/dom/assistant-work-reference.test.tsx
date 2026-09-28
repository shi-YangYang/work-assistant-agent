// @vitest-environment jsdom
import type { Conversation, Work } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setCsrf } from '../../../apps/web/src/api/client'
import { Assistant } from '../../../apps/web/src/features/assistant/components/Conversations'
import { WorkReferencePicker } from '../../../apps/web/src/features/assistant/components/WorkReferencePicker'
import { WorkReferenceChip } from '../../../apps/web/src/features/assistant/components/WorkReferenceChip'
import { useWorkReference } from '../../../apps/web/src/features/assistant/hooks/useWorkReference'
import { messageSubmission } from '../../../apps/web/src/features/assistant/utils/files'
import type { Composer } from '../../../apps/web/src/features/assistant/lib/audio-capture'
import {
  readActiveAssistantJob,
  sendMessage,
} from '../../../apps/web/src/features/assistant/api/requests'
import { useWorkspace } from '../../../apps/web/src/lib/workspace'
import { useRef } from 'react'
import { createVault, deferred, dialogs, identity, TestWorkspace } from './helpers'

vi.mock('@web/features/assistant/api/requests', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/features/assistant/api/requests')>()),
  readActiveAssistantJob: vi.fn(),
  sendMessage: vi.fn(),
}))
const work: Work = {
  id: 'work-b',
  ownerId: identity.member.id,
  title: '上线 Web',
  summary: '部署计划',
  status: 'in_progress',
  blocker: '',
  nextStep: '',
  dueDate: null,
  revision: 1,
  updatedAt: '2026-09-29T00:00:00Z',
  origin: 'manual',
}
const convo: Conversation = {
  id: 'latest-message',
  title: '最近聊天',
  revision: 1,
  updatedAt: '2026-09-29T00:00:00Z',
  personaId: 'professional',
  executionMode: 'auto',
}
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })
function RoutePage() {
  const { id } = useParams()
  const location = useLocation()
  return (
    <>
      <output aria-label="路由">
        {location.pathname}
        {location.search}
      </output>
      <Assistant conversationId={id} />
    </>
  )
}
function view(vault = createVault(), route = '/assistant?workId=work-b') {
  return (
    <TestWorkspace vault={vault}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/assistant/:id?" element={<RoutePage />} />
        </Routes>
      </MemoryRouter>
    </TestWorkspace>
  )
}
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  setCsrf('test')
  HTMLDivElement.prototype.hidePopover = vi.fn()
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: null })
  vi.mocked(sendMessage).mockResolvedValue({
    conversationId: convo.id,
    messageId: 'sent',
    jobId: 'job',
  })
  vi.stubGlobal(
    'EventSource',
    class extends EventTarget {
      close = vi.fn()
    },
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/work-items/')) return json(work)
      if (url.includes('/work-items?')) return json({ items: [work], nextCursor: null })
      if (url.includes('/context-usage')) return json({ contextUsage: null })
      if (url.includes('/conversations?order=last_message'))
        return json({ items: [convo], nextCursor: null })
      if (/\/conversations\/[^/?]+$/.test(url)) return json(convo)
      return json({ items: [], nextCursor: null })
    }),
  )
  URL.createObjectURL = vi.fn(() => 'blob:file')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('opens last messaged chat, preserves its text/files/result reference and consumes entry only once', async () => {
  const vault = createVault()
  const file = { id: 'file', file: new File(['text'], 'plan.txt'), url: 'blob:file' }
  vault.writer()('composer:new', { text: '另一个草稿', files: [], key: 'new' })
  vault.writer()(`composer:${convo.id}`, {
    text: '原草稿',
    files: [file],
    key: 'old',
    deliverableReference: { id: 'result', revision: 1, itemIds: [] },
  })
  render(view(vault))
  const input = await screen.findByRole('textbox', { name: '工作消息' })
  await screen.findByText('上线 Web')
  expect((input as HTMLTextAreaElement).value).toBe('原草稿')
  expect(document.activeElement).toBe(input)
  const draft = vault.getSnapshot()[`composer:${convo.id}`] as Composer
  expect(draft.files).toEqual([file])
  expect(draft.deliverableReference?.id).toBe('result')
  expect(draft.workReference?.workId).toBe(work.id)
  expect(screen.getByLabelText('路由').textContent).toBe(`/assistant/${convo.id}`)
  fireEvent.click(screen.getByRole('button', { name: '移除工作引用' }))
  expect(screen.queryByText('上线 Web')).toBeNull()
  expect(vault.getSnapshot()['composer:new']).toEqual({ text: '另一个草稿', files: [], key: 'new' })
  expect(sendMessage).not.toHaveBeenCalled()
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every(([, options]) => !options?.method || options.method === 'GET'),
  ).toBe(true)
})

it('keeps no-conversation entry empty, disallows reference-only send and creates only on real text', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation((url, options) =>
    String(url).includes('/conversations?order=last_message')
      ? Promise.resolve(json({ items: [] }))
      : original(url, options),
  )
  const vault = createVault()
  render(view(vault))
  await screen.findByText('上线 Web')
  expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(true)
  expect(sendMessage).not.toHaveBeenCalled()
  fireEvent.change(screen.getByRole('textbox', { name: '工作消息' }), {
    target: { value: '分析下一步' },
  })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce())
  expect(vi.mocked(sendMessage).mock.calls[0][0]).toMatchObject({
    newConversation: true,
    text: '分析下一步',
    workReference: { workId: work.id },
  })
  await waitFor(() => expect(vault.getSnapshot()['composer:new']).toBeUndefined())
})

it('plus-menu selection replaces one reference and stays in the current conversation', async () => {
  const vault = createVault()
  vault.writer()(`composer:${convo.id}`, {
    text: '分析',
    files: [],
    key: 'old',
    workReference: { workId: 'old', title: '旧工作' },
  })
  render(view(vault, `/assistant/${convo.id}`))
  await screen.findByRole('textbox', { name: '工作消息' })
  fireEvent.click(screen.getByText('引用工作'))
  await screen.findByRole('dialog', { name: '引用工作' })
  fireEvent.click(await screen.findByRole('button', { name: '引用 上线 Web' }))
  expect(screen.queryByRole('dialog', { name: '引用工作' })).toBeNull()
  expect(screen.queryByText('旧工作')).toBeNull()
  expect(screen.getByText('上线 Web')).toBeTruthy()
  expect(document.activeElement).toBe(screen.getByRole('textbox', { name: '工作消息' }))
  expect(screen.getByLabelText('路由').textContent).toBe(`/assistant/${convo.id}`)
  expect((vault.getSnapshot()[`composer:${convo.id}`] as Composer).workReference).toEqual({
    workId: work.id,
    title: work.title,
  })
})

it('removing the only reference clears an otherwise empty draft', async () => {
  const vault = createVault()
  vault.writer()(`composer:${convo.id}`, {
    text: '',
    files: [],
    key: 'ref',
    workReference: { workId: work.id, title: work.title },
  })
  render(view(vault, `/assistant/${convo.id}`))
  fireEvent.click(await screen.findByRole('button', { name: '移除工作引用' }))
  expect(vault.getSnapshot()[`composer:${convo.id}`]).toBeUndefined()
  expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(true)
})

it('queues an entry behind an uncertain request without changing its payload or idempotency key', async () => {
  const vault = createVault()
  const old = {
    text: '此前请求',
    files: [],
    key: 'frozen',
    workReference: { workId: 'work-a', title: '旧工作' },
  }
  const pending = messageSubmission(old, convo.id, 'professional')
  vault.writer()(`composer:${convo.id}`, { ...old, pending })
  const sent = deferred<{ conversationId: string; messageId: string; jobId: string }>()
  vi.mocked(sendMessage).mockReturnValue(sent.promise)
  render(view(vault))
  await screen.findByRole('button', { name: '原样重试，确认结果' })
  await waitFor(() =>
    expect(
      vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/work-items/work-b')),
    ).toBe(true),
  )
  expect((vault.getSnapshot()[`composer:${convo.id}`] as Composer).pending).toEqual(pending)
  expect(screen.queryByText('上线 Web')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '原样重试，确认结果' }))
  expect(sendMessage).toHaveBeenCalledWith(pending.body, pending.key)
  await act(async () => sent.resolve({ conversationId: convo.id, messageId: 'sent', jobId: 'job' }))
  await screen.findByText('上线 Web')
  const next = vault.getSnapshot()[`composer:${convo.id}`] as Composer
  expect(next.text).toBe('')
  expect(next.pending).toBeUndefined()
  expect(next.workReference?.workId).toBe('work-b')
  expect(screen.getByLabelText('路由').textContent).toBe(`/assistant/${convo.id}`)
})

it('preserves reference and exact payload on uncertain failure, then clears on accepted retry', async () => {
  const vault = createVault()
  vault.writer()(`composer:${convo.id}`, {
    text: '分析',
    files: [],
    key: 'stable',
    workReference: { workId: work.id, title: work.title },
  })
  vi.mocked(sendMessage).mockRejectedValueOnce(new Error('网络中断'))
  render(view(vault, `/assistant/${convo.id}`))
  fireEvent.click(await screen.findByRole('button', { name: '发送' }))
  await screen.findByRole('button', { name: '原样重试，确认结果' })
  expect(screen.getByRole('button', { name: '移除工作引用' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByText('上线 Web')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '原样重试，确认结果' }))
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2))
  expect(vi.mocked(sendMessage).mock.calls[1]).toEqual(vi.mocked(sendMessage).mock.calls[0])
  await waitFor(() => expect(vault.getSnapshot()[`composer:${convo.id}`]).toBeUndefined())
})

it('searches server data and loads another page, including completed work', async () => {
  const selected = vi.fn()
  vi.mocked(fetch).mockImplementation(async (url) => {
    const path = String(url)
    if (path.includes('q=%E5%B7%B2%E5%AE%8C%E6%88%90'))
      return json({ items: [{ ...work, title: '已完成工作', status: 'done' }] })
    if (path.includes('cursor=next'))
      return json({ items: [{ ...work, id: 'older', title: '第二页工作' }] })
    return json({ items: [work], nextCursor: 'next' })
  })
  render(<WorkReferencePicker onClose={vi.fn()} onSelect={selected} />)
  fireEvent.click(await screen.findByRole('button', { name: '加载更多' }))
  fireEvent.click(await screen.findByRole('button', { name: '引用 第二页工作' }))
  expect(selected.mock.calls[0][0].id).toBe('older')
  fireEvent.change(screen.getByRole('textbox', { name: '搜索工作' }), {
    target: { value: '已完成' },
  })
  const done = await screen.findByRole('button', { name: '引用 已完成工作' })
  done.focus()
  expect(document.activeElement).toBe(done)
  fireEvent.click(done)
  expect(selected.mock.calls[1][0].status).toBe('done')
})

it('never applies a delayed work entry to another account or conversation', async () => {
  const slow = deferred<Response>()
  vi.mocked(fetch).mockReturnValue(slow.promise)
  function Hook({ draftKey }: { draftKey: string }) {
    const input = useRef<HTMLTextAreaElement>(null)
    useWorkReference(draftKey, false, input)
    const { drafts } = useWorkspace()
    return <output>{JSON.stringify(drafts)}</output>
  }
  const vault = createVault()
  const renderHook = (key: string) => (
    <TestWorkspace vault={vault}>
      <MemoryRouter initialEntries={['/assistant?workId=work-b']}>
        <Hook draftKey={key} />
      </MemoryRouter>
    </TestWorkspace>
  )
  const mounted = render(renderHook('composer:first'))
  mounted.rerender(renderHook('composer:second'))
  await act(async () => slow.resolve(json(work)))
  await waitFor(() =>
    expect((vault.getSnapshot()['composer:second'] as Composer)?.workReference?.workId).toBe(
      work.id,
    ),
  )
  expect(vault.getSnapshot()['composer:first']).toBeUndefined()
  const later = deferred<Response>()
  vi.mocked(fetch).mockReturnValue(later.promise)
  cleanup()
  render(renderHook('composer:third'))
  act(() => {
    vault.clear()
    vault.resume({ ...identity, member: { ...identity.member, id: 'another' } })
    setCsrf('other')
  })
  await act(async () => later.resolve(json(work)))
  expect(vault.getSnapshot()).toEqual({})
})

it('renders a valid sent reference as a link, and an unavailable reference without its title', () => {
  render(
    <MemoryRouter>
      <WorkReferenceChip linked reference={{ workId: work.id, title: work.title }} />
      <WorkReferenceChip
        linked
        reference={{ workId: 'deleted', title: '不能泄露', unavailable: true }}
      />
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: '上线 Web' }).getAttribute('href')).toBe('/work/work-b')
  expect(screen.getByText('工作不可用')).toBeTruthy()
  expect(screen.queryByText('不能泄露')).toBeNull()
})
