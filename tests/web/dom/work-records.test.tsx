// @vitest-environment jsdom
import type { Attachment, Work, WorkWriteResult } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, ApiError, write } from '../../../apps/web/src/api/client'
import { DocumentCard } from '../../../apps/web/src/components/media/Documents'
import { WorkEditor } from '../../../apps/web/src/features/work/components/editor/WorkEditor'
import { CreateWork } from '../../../apps/web/src/features/work/components/editor/CreateWork'
import { WorkContent } from '../../../apps/web/src/features/work/components/content/WorkContent'
import { UpdateEditor } from '../../../apps/web/src/features/work/components/updates/UpdateEditor'
import { WorkUpdates } from '../../../apps/web/src/features/work/components/updates/WorkUpdates'
import { documentFromText } from '../../../apps/web/src/features/work/utils/document'
import { createVault, deferred, dialogs, TestWorkspace } from './helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))
const work: Work = {
  id: 'work',
  ownerId: 'owner',
  title: '官网改版',
  summary: '',
  status: 'in_progress',
  blocker: '',
  nextStep: '',
  revision: 1,
  updatedAt: '2026-10-01T01:00:00Z',
  body: documentFromText('目标与计划'),
  materialIds: [],
}
const renderWork = (node: React.ReactNode, vault = createVault()) =>
  render(
    <MemoryRouter>
      <TestWorkspace vault={vault}>{node}</TestWorkspace>
    </MemoryRouter>,
  )
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  vi.mocked(api).mockResolvedValue({ items: [], nextCursor: null })
})
afterEach(cleanup)
it('creates from a title and does not ask for progress or create fake updates', async () => {
  const saved = vi.fn()
  vi.mocked(write).mockResolvedValue(work)
  renderWork(<CreateWork onClose={vi.fn()} onSaved={saved} />)
  expect(screen.queryByLabelText('当前进展')).toBeNull()
  fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
    target: { value: '官网改版' },
  })
  fireEvent.click(screen.getByRole('button', { name: '创建工作' }))
  await waitFor(() => expect(saved).toHaveBeenCalledWith(work))
  expect(write).toHaveBeenCalledWith(
    '/work-items',
    { title: '官网改版', dueDate: null },
    'POST',
    expect.any(String),
  )
})
it('saves a separate update with stable key after lost response while preserving the work body', async () => {
  const saved = vi.fn(),
    vault = createVault()
  vi.mocked(write)
    .mockRejectedValueOnce(new Error('网络中断'))
    .mockResolvedValueOnce({ work } as WorkWriteResult)
  renderWork(<UpdateEditor work={work} close={vi.fn()} saved={saved} />, vault)
  fireEvent.change(screen.getByLabelText('记录新进展'), { target: { value: '客户确认初稿' } })
  fireEvent.click(screen.getByRole('button', { name: '保存进展' }))
  await screen.findByText('网络中断')
  const first = vi.mocked(write).mock.calls[0]
  expect(first[1]).toMatchObject({ text: '客户确认初稿', expectedRevision: 1, materials: [] })
  expect(first[1]).not.toHaveProperty('body')
  fireEvent.click(screen.getByRole('button', { name: '保存进展' }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(vi.mocked(write).mock.calls[1]).toEqual(first)
  expect(vault.getSnapshot()['work:update:work:new']).toBeUndefined()
})
it('keeps an attachment-only progress draft valid and only binds when saved', async () => {
  const vault = createVault(),
    saved = vi.fn()
  vault.writer()('work:update:work:new', {
    text: '',
    files: [
      {
        id: 'upload',
        kind: 'image',
        name: '需求.png',
        mime: 'image/png',
        url: '/uploads/upload',
        size: 12,
        duration: null,
      },
    ],
    materialIds: [],
    revision: 1,
    key: 'upload-save',
    properties: {},
  })
  vi.mocked(write).mockResolvedValue({ work })
  renderWork(<UpdateEditor work={work} close={vi.fn()} saved={saved} />, vault)
  expect(write).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '保存进展' }))
  await waitFor(() => expect(saved).toHaveBeenCalled())
  expect(write).toHaveBeenCalledWith(
    '/work-items/work/updates',
    expect.objectContaining({ text: '', materials: [{ attachmentId: 'upload' }] }),
    'POST',
    'upload-save',
  )
})
it('retains failed rich body draft and retries without losing its material sources', async () => {
  const saved = vi.fn(),
    vault = createVault()
  const file: Attachment = {
    id: 'body-upload',
    kind: 'document',
    name: '需求.txt',
    mime: 'text/plain',
    url: '/uploads/body-upload',
    size: 20,
    duration: null,
    extraction: { status: 'pending', revision: 0, parserVersion: '' },
  }
  vault.writer()('work:body:work', {
    body: {
      schemaVersion: 1,
      content: [
        ...documentFromText('尚未保存的方案').content,
        { type: 'material', attrs: { materialId: file.id } },
      ],
    },
    files: [file],
    revision: 1,
    key: 'body-save',
  })
  vi.mocked(write).mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce({ work })
  renderWork(<WorkContent work={work} own saved={saved} />, vault)
  fireEvent.click(screen.getByRole('button', { name: '编辑正文' }))
  expect(await screen.findByText('尚未保存的方案')).toBeTruthy()
  const submittedDraft = vault.getSnapshot()['work:body:work'] as { key: string }
  fireEvent.click(screen.getByRole('button', { name: '保存正文' }))
  await screen.findByText('网络中断')
  expect(vault.getSnapshot()['work:body:work']).toEqual(submittedDraft)
  expect(screen.getByRole('button', { name: '移除 需求.txt' })).toBeTruthy()
  expect(saved).not.toHaveBeenCalled()
  expect(write).toHaveBeenCalledWith(
    '/work-items/work',
    expect.objectContaining({
      expectedRevision: 1,
      body: expect.objectContaining({
        content: expect.arrayContaining([
          expect.objectContaining({
            type: 'paragraph',
            content: [{ type: 'text', text: '尚未保存的方案' }],
          }),
          expect.objectContaining({
            type: 'material',
            attrs: expect.objectContaining({ materialId: file.id }),
          }),
        ]),
      }),
      materials: [{ attachmentId: file.id }],
    }),
    'PATCH',
    submittedDraft.key,
  )
  const first = vi.mocked(write).mock.calls[0]
  fireEvent.click(screen.getByRole('button', { name: '保存正文' }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(write).toHaveBeenCalledTimes(2)
  expect(vi.mocked(write).mock.calls[1]).toEqual(first)
  expect(vault.getSnapshot()['work:body:work']).toBeUndefined()
  expect(screen.queryByRole('button', { name: '移除 需求.txt' })).toBeNull()
})
it('does not show write actions for another owner or a historical version', async () => {
  renderWork(<WorkUpdates work={{ ...work, historical: true }} own={false} saved={vi.fn()} />)
  await screen.findByText(/还没有进展记录/)
  expect(screen.queryByRole('button', { name: '记录新进展' })).toBeNull()
  expect(api).toHaveBeenCalledWith(
    '/work-items/work/updates?start=0&limit=20&revision=1',
    expect.anything(),
  )
})
it('holds a pending creation to one request', async () => {
  const request = deferred<Work>()
  vi.mocked(write).mockReturnValue(request.promise)
  renderWork(<CreateWork onClose={vi.fn()} onSaved={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
    target: { value: '一次创建' },
  })
  fireEvent.submit(screen.getByRole('textbox', { name: '工作事项' }).closest('form')!)
  fireEvent.submit(screen.getByRole('textbox', { name: '工作事项' }).closest('form')!)
  expect(write).toHaveBeenCalledTimes(1)
  await act(async () => request.resolve(work))
})

it('replays only the changed metadata after reviewing a concurrent server update', async () => {
  const saved = vi.fn()
  const latest = { ...work, revision: 2, dueDate: '2026-10-06', status: 'done' as const }
  vi.mocked(api).mockResolvedValue(latest)
  vi.mocked(write)
    .mockRejectedValueOnce(new ApiError(409, 'conflict', '内容已变化'))
    .mockResolvedValueOnce({ work: { ...latest, title: '新的标题' } })
  renderWork(<WorkEditor work={work} onClose={vi.fn()} onSaved={saved} />)
  fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
    target: { value: '新的标题' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存属性' }))
  await screen.findByText('内容已变化')
  fireEvent.click(screen.getByRole('button', { name: '读取最新版本' }))
  fireEvent.click(await screen.findByRole('button', { name: '保留当前输入，继续编辑' }))
  expect(screen.getByLabelText('截止日期（选填）').getAttribute('value')).toBe('2026-10-06')
  fireEvent.click(screen.getByRole('button', { name: '保存属性' }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(vi.mocked(write).mock.calls[1][1]).toEqual({ title: '新的标题', expectedRevision: 2 })
})
it('does not submit a work form when refreshing a material preview', () => {
  const submit = vi.fn((event: React.FormEvent) => event.preventDefault())
  const refresh = vi.fn()
  const attachment = {
    id: 'upload',
    kind: 'document',
    name: '需求.txt',
    size: 20,
    mime: 'text/plain',
    url: '/uploads/upload',
    extraction: { status: 'pending' },
  } as Attachment
  render(
    <form onSubmit={submit}>
      <DocumentCard attachment={attachment} own refresh={refresh} />
    </form>,
  )
  fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  expect(refresh).toHaveBeenCalledOnce()
  expect(submit).not.toHaveBeenCalled()
})
