// @vitest-environment jsdom
import type { Attachment, Conversation } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../../apps/web/src/api/client'
import {
  readConversation,
  readActiveAssistantJob,
  sendMessage,
  updateConversationPersona,
  uploadAttachment,
} from '../../../apps/web/src/features/assistant/api/requests'
import { Assistant } from '../../../apps/web/src/features/assistant/components/conversation/Conversations'
import { PersonaPicker } from '../../../apps/web/src/features/assistant/components/conversation/PersonaPicker'
import { useConversationPersona } from '../../../apps/web/src/features/assistant/hooks/useConversationPersona'
import type { Composer } from '../../../apps/web/src/features/assistant/lib/audio-capture'
import { createVault, deferred, dialogs, identity, TestWorkspace } from './helpers'

vi.mock('@web/features/assistant/api/requests', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/features/assistant/api/requests')>()),
  updateConversationPersona: vi.fn(),
  readConversation: vi.fn(),
  readActiveAssistantJob: vi.fn(),
  sendMessage: vi.fn(),
  uploadAttachment: vi.fn(),
}))
const conversation: Conversation = {
  id: 'first',
  title: '已保存的会话',
  revision: 1,
  updatedAt: '2026-09-01T00:00:00Z',
  personaId: 'professional',
}
function choose(name: string) {
  fireEvent.click(screen.getByRole('button', { name: /^选择人设/ }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: new RegExp(name) }))
}
function HookPage({ value }: { value: Conversation | null }) {
  const persona = useConversationPersona(value?.id, value, vi.fn())
  return (
    <>
      <PersonaPicker
        value={persona.selected}
        disabled={persona.disabled || !!persona.interaction.busy}
        onChange={(next) => void persona.choose(next)}
      />
      {persona.error && <p role="alert">{String(persona.error)}</p>}
    </>
  )
}
function AssistantRoute() {
  const { id } = useParams()
  return <Assistant conversationId={id} />
}
function assistantView(vault = createVault(), route = '/assistant?new=1') {
  return (
    <TestWorkspace vault={vault}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/assistant/:id?" element={<AssistantRoute />} />
        </Routes>
      </MemoryRouter>
    </TestWorkspace>
  )
}
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: null })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const path = url.replace('/api/v1', '')
      const body = path.startsWith('/conversations/')
        ? { ...conversation, id: path.split('/')[2] }
        : { items: [], nextCursor: null }
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  vi.stubGlobal(
    'EventSource',
    class extends EventTarget {
      close = vi.fn()
    },
  )
  URL.createObjectURL = vi.fn(() => 'blob:attachment')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('supports keyboard selection, checked state, Escape, outside close and focus return', () => {
  function Picker() {
    const [value, setValue] = useState<'dabao' | 'professional'>('dabao')
    return <PersonaPicker value={value} disabled={false} onChange={setValue} />
  }
  render(<Picker />)
  const trigger = screen.getByRole('button', { name: '选择人设：Noria人设' })
  fireEvent.keyDown(trigger, { key: 'ArrowDown' })
  const dabao = screen.getByRole('menuitemradio', { name: /Noria人设/ })
  const professional = screen.getByRole('menuitemradio', { name: /专业人设/ })
  expect(dabao.getAttribute('aria-checked')).toBe('true')
  expect(document.activeElement).toBe(dabao)
  fireEvent.keyDown(dabao, { key: 'ArrowDown' })
  expect(document.activeElement).toBe(professional)
  fireEvent.click(professional)
  expect(screen.queryByRole('menu')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  expect(trigger.textContent).toBe('专业人设')
  fireEvent.click(trigger)
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
  expect(document.activeElement).toBe(trigger)
  expect(screen.queryByRole('menu')).toBeNull()
  fireEvent.click(trigger)
  fireEvent.pointerDown(document.body)
  expect(screen.queryByRole('menu')).toBeNull()
})

it('keeps an empty choice with its draft across remounts and makes no conversation or model request', () => {
  const vault = createVault()
  const view = render(assistantView(vault))
  choose('专业人设')
  expect(updateConversationPersona).not.toHaveBeenCalled()
  expect(sendMessage).not.toHaveBeenCalled()
  expect(fetch).not.toHaveBeenCalled()
  fireEvent.change(screen.getByRole('textbox', { name: '工作消息' }), {
    target: { value: '保留草稿' },
  })
  view.unmount()
  render(assistantView(vault))
  expect(screen.getByRole('button', { name: '选择人设：专业人设' })).toBeTruthy()
  expect((screen.getByRole('textbox', { name: '工作消息' }) as HTMLTextAreaElement).value).toBe(
    '保留草稿',
  )
  expect(vault.getSnapshot()['composer:new']).toMatchObject({ personaId: 'professional' })
})

it('restores a confirmed choice after save failure, preserves text/files and prevents conflicting sends', async () => {
  const request = deferred<Conversation>(),
    vault = createVault()
  const file = { id: 'file', file: new File(['data'], 'notes.txt'), url: 'blob:file' }
  vault.writer()('composer:first', { text: '待发送草稿', files: [file], key: 'draft' })
  vi.mocked(updateConversationPersona).mockReturnValue(request.promise)
  render(assistantView(vault, '/assistant/first'))
  await screen.findByRole('textbox', { name: '工作消息' })
  choose('Noria人设')
  expect(updateConversationPersona).toHaveBeenCalledWith(conversation, {
    personaId: 'dabao',
    expectedRevision: 1,
  })
  expect(
    (screen.getByRole('button', { name: '选择人设：Noria人设' }) as HTMLButtonElement).disabled,
  ).toBe(true)
  expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.keyDown(screen.getByRole('textbox', { name: '工作消息' }), { key: 'Enter' })
  expect(sendMessage).not.toHaveBeenCalled()
  await act(async () => request.reject(new Error('保存失败')))
  expect(screen.getByRole('button', { name: '选择人设：专业人设' })).toBeTruthy()
  expect(screen.getByText('保存失败')).toBeTruthy()
  expect(vault.getSnapshot()['composer:first']).toMatchObject({ text: '待发送草稿', files: [file] })
})

it('reloads the current revision on conflict, then saves against that version', async () => {
  const vault = createVault()
  vi.mocked(updateConversationPersona)
    .mockRejectedValueOnce(new ApiError(409, 'revision_conflict', '内容已变化', 'conflict'))
    .mockResolvedValueOnce({ ...conversation, revision: 3, personaId: 'dabao' })
  vi.mocked(readConversation).mockResolvedValue({ ...conversation, revision: 2 })
  render(
    <TestWorkspace vault={vault}>
      <HookPage value={conversation} />
    </TestWorkspace>,
  )
  choose('Noria人设')
  await screen.findByRole('alert')
  await waitFor(() =>
    expect((screen.getByRole('button', { name: /^选择人设/ }) as HTMLButtonElement).disabled).toBe(
      false,
    ),
  )
  choose('Noria人设')
  await waitFor(() =>
    expect(updateConversationPersona).toHaveBeenLastCalledWith(
      { ...conversation, revision: 2 },
      { personaId: 'dabao', expectedRevision: 2 },
    ),
  )
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
})

it.each(['conversation', 'account'] as const)(
  'ignores late saves after changing %s',
  async (change) => {
    const request = deferred<Conversation>(),
      vault = createVault()
    vi.mocked(updateConversationPersona).mockReturnValue(request.promise)
    const view = (record = conversation, account = identity) => (
      <TestWorkspace vault={vault} account={account}>
        <HookPage value={record} />
      </TestWorkspace>
    )
    const mounted = render(view())
    choose('Noria人设')
    const account =
      change === 'account'
        ? { ...identity, member: { ...identity.member, id: 'another' } }
        : identity
    const record = change === 'conversation' ? { ...conversation, id: 'second' } : conversation
    if (change === 'account') act(() => vault.resume(account))
    mounted.rerender(view(record, account))
    await act(async () => request.resolve({ ...conversation, personaId: 'dabao', revision: 2 }))
    expect(screen.getByRole('button', { name: '选择人设：专业人设' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
    expect((screen.getByRole('button', { name: /^选择人设/ }) as HTMLButtonElement).disabled).toBe(
      false,
    )
  },
)

it('does not overwrite a newer record response with an older save response', async () => {
  const request = deferred<Conversation>(),
    vault = createVault()
  vi.mocked(updateConversationPersona).mockReturnValue(request.promise)
  const view = (record: Conversation) => (
    <TestWorkspace vault={vault}>
      <HookPage value={record} />
    </TestWorkspace>
  )
  const mounted = render(view(conversation))
  choose('Noria人设')
  mounted.rerender(view({ ...conversation, revision: 3 }))
  await act(async () => request.resolve({ ...conversation, personaId: 'dabao', revision: 2 }))
  expect(screen.getByRole('button', { name: '选择人设：专业人设' })).toBeTruthy()
})

it('freezes the persona before upload and reuses the same pending body after a later selection change', async () => {
  const upload = deferred<Attachment>(),
    firstSend = deferred<{ conversationId: string; messageId: string; jobId: string }>(),
    vault = createVault()
  vault.writer()('composer:new', {
    text: '带附件发送',
    key: 'frozen-request',
    files: [
      {
        id: 'local-file',
        file: new File(['data'], 'notes.txt'),
        url: 'blob:file',
      },
    ],
  })
  vi.mocked(uploadAttachment).mockReturnValue(upload.promise)
  vi.mocked(sendMessage)
    .mockReturnValueOnce(firstSend.promise)
    .mockResolvedValueOnce({ conversationId: 'created', messageId: 'message', jobId: 'job' })
  render(assistantView(vault))
  choose('专业人设')
  const sendButton = screen.getByRole('button', { name: '发送' })
  const contextButton = screen.getByRole('button', { name: /^上下文使用情况/ })
  const sendIcon = sendButton.querySelector('svg')
  fireEvent.click(sendButton)
  expect(vault.getSnapshot()['composer:new']).toMatchObject({
    submissionPersonaId: 'professional',
    sending: true,
  })
  expect((screen.getByRole('button', { name: /^选择人设/ }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  await act(async () =>
    upload.resolve({
      id: 'uploaded',
      kind: 'document',
      name: 'notes.txt',
      url: '/file',
      mime: 'text/plain',
      size: 4,
    } as Attachment),
  )
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1))
  const sendingButton = screen.getByRole('button', { name: '正在发送' })
  expect(sendingButton).toBe(sendButton)
  expect(sendingButton.getAttribute('data-expanded')).toBe('false')
  expect(sendingButton.querySelector('svg')).toBe(sendIcon)
  expect(screen.queryByText('原样重试，确认结果')).toBeNull()
  expect(screen.getByRole('button', { name: /^上下文使用情况/ })).toBe(contextButton)
  const [body, key] = vi.mocked(sendMessage).mock.calls[0]
  expect(body).toMatchObject({
    personaId: 'professional',
    newConversation: true,
    attachmentIds: ['uploaded'],
  })
  await act(async () => firstSend.reject(new Error('网络连接中断')))
  expect(
    screen.getByRole('button', { name: '原样重试，确认结果' }).getAttribute('data-expanded'),
  ).toBe('false')
  choose('Noria人设')
  expect((vault.getSnapshot()['composer:new'] as Composer).pending?.body.personaId).toBe(
    'professional',
  )
  fireEvent.click(screen.getByRole('button', { name: '原样重试，确认结果' }))
  await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2))
  expect(vi.mocked(sendMessage).mock.calls[1][0]).toBe(body)
  expect(vi.mocked(sendMessage).mock.calls[1][1]).toBe(key)
  expect(uploadAttachment).toHaveBeenCalledTimes(1)
  await waitFor(() => expect(vault.getSnapshot()['composer:new']).toBeUndefined())
})

it('isolates an empty draft choice between accounts and restores a persisted server choice', () => {
  const vault = createVault()
  const view = (account = identity, record: Conversation | null = null) => (
    <TestWorkspace vault={vault} account={account}>
      <HookPage value={record} />
    </TestWorkspace>
  )
  const mounted = render(view())
  choose('专业人设')
  const other = { ...identity, member: { ...identity.member, id: 'another' } }
  act(() => vault.resume(other))
  mounted.rerender(view(other))
  expect(screen.getByRole('button', { name: '选择人设：Noria人设' })).toBeTruthy()
  mounted.rerender(view(other, { ...conversation, personaId: 'dabao' }))
  expect(screen.getByRole('button', { name: '选择人设：Noria人设' })).toBeTruthy()
  expect(updateConversationPersona).not.toHaveBeenCalled()
})

it('preserves the preview upload lock when leaving and returning to the draft', async () => {
  const upload = deferred<Attachment>(),
    vault = createVault()
  vault.writer()('composer:new', {
    text: '图片草稿',
    key: 'image-draft',
    files: [
      {
        id: 'image',
        file: new File(['data'], 'image.heic'),
        url: 'blob:image',
      },
    ],
  })
  vi.mocked(uploadAttachment).mockReturnValue(upload.promise)
  const mounted = render(assistantView(vault))
  fireEvent.click(screen.getByRole('button', { name: '预览image.heic' }))
  fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
  expect(vault.getSnapshot()['composer:new']).toMatchObject({ uploading: 'image' })
  mounted.unmount()
  render(assistantView(vault))
  expect((screen.getByRole('button', { name: /^选择人设/ }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () =>
    upload.resolve({
      id: 'uploaded',
      kind: 'image',
      name: 'image.heic',
      url: '/image',
      previewUrl: '/preview',
      mime: 'image/heic',
      size: 4,
    } as Attachment),
  )
  expect((screen.getByRole('button', { name: /^选择人设/ }) as HTMLButtonElement).disabled).toBe(
    false,
  )
  expect(vault.getSnapshot()['composer:new']).toMatchObject({
    text: '图片草稿',
    files: [{ attachment: { id: 'uploaded' } }],
  })
})
