// @vitest-environment jsdom
import type { Attachment, Work } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { uploadAttachment } from '../../../../apps/web/src/api/attachments'
import { api, ApiError, write } from '../../../../apps/web/src/api/client'
import { DocumentCard } from '../../../../apps/web/src/components/media/Documents'
import { WorkEditor } from '../../../../apps/web/src/features/work/components/editor/WorkEditor'
import { CreateWork } from '../../../../apps/web/src/features/work/components/editor/CreateWork'
import { WorkContent } from '../../../../apps/web/src/features/work/components/content/WorkContent'
import { WorkHistory } from '../../../../apps/web/src/features/work/components/detail/WorkHistory'
import { WorkDetail } from '../../../../apps/web/src/features/work/components/detail/WorkDetail'
import { documentFromText } from '../../../../apps/web/src/features/work/utils/document'
import { createVault, deferred, dialogs, TestWorkspace } from '../helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))
vi.mock('@web/api/attachments', () => ({ uploadAttachment: vi.fn() }))
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
const renderWork = (node: React.ReactNode, vault = createVault(), entry = '/work/work') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <TestWorkspace vault={vault}>{node}</TestWorkspace>
    </MemoryRouter>,
  )
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  vi.mocked(api).mockResolvedValue({ items: [], nextCursor: null })
})
afterEach(cleanup)
it('returns through historical versions to the latest work without losing the return path', async () => {
  const history = [3, 2, 1].map((revision) => ({
    id: `r${revision}`,
    revision,
    content: { ...work, title: `标题 ${revision}` },
    sourceIds: [],
    createdAt: work.updatedAt,
  }))
  vi.mocked(api).mockImplementation(async (path) => {
    const requested = new URL(String(path), 'http://local').searchParams.get('revision')
    const revision = Number(requested ?? 3)
    return {
      ...work,
      revision,
      historical: !!requested,
      history: history.filter((row) => row.revision <= revision),
    }
  })
  renderWork(<WorkDetail recordId="work" />)
  await screen.findByRole('heading', { name: work.title })
  fireEvent.click(screen.getAllByRole('link', { name: '查看当时内容' })[1])
  await waitFor(() =>
    expect(api).toHaveBeenLastCalledWith('/work-items/work?revision=2', expect.anything()),
  )
  fireEvent.click(screen.getAllByRole('link', { name: '查看当时内容' })[1])
  await waitFor(() =>
    expect(api).toHaveBeenLastCalledWith('/work-items/work?revision=1', expect.anything()),
  )
  expect(screen.queryByRole('region', { name: '修改记录' })).toBeNull()
  fireEvent.click(screen.getByRole('link', { name: '返回上一步' }))
  await waitFor(() =>
    expect(api).toHaveBeenLastCalledWith('/work-items/work?revision=2', expect.anything()),
  )
  fireEvent.click(screen.getByRole('link', { name: '返回当前工作' }))
  const editContent = await screen.findByRole('button', { name: '编辑内容' })
  expect(editContent.closest('header')).toBeTruthy()
  expect(
    within(screen.getByRole('region', { name: '工作内容' })).queryByRole('button', {
      name: '编辑内容',
    }),
  ).toBeNull()
  fireEvent.click(editContent)
  expect(screen.getByRole('textbox', { name: '工作正文' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(screen.getByRole('button', { name: '编辑内容' }).closest('header')).toBeTruthy()
  expect(screen.queryByText(/当时内容 ·/)).toBeNull()
})

it('lists uploaded materials below the text editor and excludes removed files from the save', async () => {
  const file = (id: string): Attachment => ({
    id,
    kind: 'image',
    name: `${id}.png`,
    mime: 'image/png',
    size: 12,
    duration: null,
    url: `/uploads/${id}`,
  })
  vi.mocked(uploadAttachment)
    .mockResolvedValueOnce(file('first'))
    .mockResolvedValueOnce(file('second'))
  const saved = vi.fn()
  vi.mocked(write).mockResolvedValue({ work })
  renderWork(<WorkContent work={work} own saved={saved} />)
  fireEvent.click(screen.getByRole('button', { name: '编辑内容' }))
  fireEvent.change(screen.getByLabelText('正文材料'), {
    target: {
      files: [
        new File(['a'], 'first.png', { type: 'image/png' }),
        new File(['b'], 'second.png', { type: 'image/png' }),
      ],
    },
  })
  const materials = await screen.findByRole('region', { name: '内容材料' })
  await within(materials).findByText('second.png')
  const editor = screen.getByRole('textbox', { name: '工作正文' })
  expect(editor.textContent).toBe('目标与计划')
  expect(editor.querySelector('[data-work-material]')).toBeNull()
  fireEvent.click(within(materials).getByRole('button', { name: '移除 first.png' }))
  fireEvent.click(screen.getByRole('button', { name: '保存内容' }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  const payload = vi.mocked(write).mock.calls[0][1] as { body: Work['body']; materials: unknown[] }
  expect(payload.materials).toEqual([{ attachmentId: 'second' }])
  expect(JSON.stringify(payload.body)).toContain('second')
  expect(JSON.stringify(payload.body)).not.toContain('first')
})

it('keeps existing material references when editing text without rendering them in the textbox', async () => {
  const body: NonNullable<Work['body']> = {
    schemaVersion: 1,
    content: [
      ...work.body!.content,
      { type: 'material', attrs: { id: 'stable-block', materialId: 'existing' } },
    ],
  }
  vi.mocked(api).mockResolvedValue({ id: 'existing', attachment: { name: '需求.txt', size: 20 } })
  vi.mocked(write).mockResolvedValue({ work })
  const saved = vi.fn()
  renderWork(<WorkContent work={{ ...work, body }} own saved={saved} />)
  fireEvent.click(screen.getByRole('button', { name: '编辑内容' }))
  expect(
    await within(screen.getByRole('region', { name: '内容材料' })).findByRole('button', {
      name: '需求.txt',
    }),
  ).toBeTruthy()
  expect(
    screen.getByRole('textbox', { name: '工作正文' }).querySelector('[data-work-material]'),
  ).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '保存内容' }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(write).toHaveBeenCalledWith(
    '/work-items/work',
    expect.objectContaining({
      body: expect.objectContaining({
        content: expect.arrayContaining([
          { type: 'material', attrs: { id: 'stable-block', materialId: 'existing' } },
        ]),
      }),
      materials: [],
    }),
    'PATCH',
    expect.any(String),
  )
})

it('omits history for a newly created work and opens material tools on demand', async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/work-items/work')
      return {
        ...work,
        materialIds: ['material'],
        history: [
          { id: 'r1', revision: 1, content: work, sourceIds: [], createdAt: work.updatedAt },
        ],
      }
    if (String(path).includes('/materials'))
      return {
        items: [{ id: 'material', attachment: { name: '需求.txt', size: 20 } }],
        nextCursor: null,
      }
    return { items: [], nextCursor: null }
  })
  renderWork(<WorkDetail recordId="work" />)
  await screen.findByRole('heading', { name: work.title })
  expect(screen.getByText('目标与计划')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '记录新进展' })).toBeNull()
  expect(screen.queryByRole('region', { name: '修改记录' })).toBeNull()
  expect(screen.queryByRole('link', { name: '查看当时内容' })).toBeNull()
  expect(vi.mocked(api).mock.calls.some(([path]) => String(path).includes('/updates'))).toBe(false)
  expect(screen.queryByText('修改记录与来源')).toBeNull()
  expect(vi.mocked(api).mock.calls.some(([path]) => String(path).includes('/materials'))).toBe(
    false,
  )

  fireEvent.click(screen.getByRole('button', { name: '全部附件 · 1' }))
  const materials = screen.getByRole('dialog', { name: '全部附件' })
  expect(await within(materials).findByRole('button', { name: '需求.txt' })).toBeTruthy()
  fireEvent.click(within(materials).getByRole('button', { name: '关闭' }))

  fireEvent.click(screen.getByRole('button', { name: '管理工作' }))
  fireEvent.click(screen.getByRole('menuitem', { name: '编辑工作属性' }))
  const properties = screen.getByRole('dialog', { name: '编辑工作属性' })
  fireEvent.click(within(properties).getByRole('button', { name: '关闭' }))

  expect(write).not.toHaveBeenCalled()
})
it('keeps older modifications available without expanding every field change', () => {
  renderWork(
    <WorkHistory
      work={{
        ...work,
        revision: 6,
        history: Array.from({ length: 6 }, (_, index) => ({
          id: `r${6 - index}`,
          revision: 6 - index,
          content: { ...work, title: `工作版本 ${6 - index}` },
          sourceIds: [],
          createdAt: work.updatedAt,
        })),
      }}
    />,
  )
  expect(screen.getAllByRole('link', { name: '查看当时内容' })).toHaveLength(3)
  fireEvent.click(screen.getByRole('button', { name: '查看更早的 3 条修改' }))
  expect(screen.getAllByRole('link', { name: '查看当时内容' })).toHaveLength(6)
})
it('keeps historical work read-only without empty history', async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    String(path).includes('/materials')
      ? {
          items: [{ id: 'material', attachment: { name: '历史材料.txt', size: 20 } }],
          nextCursor: null,
        }
      : { ...work, historical: true, materialIds: ['material'] },
  )
  renderWork(<WorkDetail recordId="work" />)
  await screen.findByRole('heading', { name: work.title })
  expect(screen.queryByRole('button', { name: '管理工作' })).toBeNull()
  expect(screen.queryByRole('region', { name: '修改记录' })).toBeNull()
  expect(screen.getByRole('link', { name: '返回当前工作' }).getAttribute('href')).toBe('/work/work')
  expect(screen.queryByRole('menuitem', { name: '编辑工作属性' })).toBeNull()
  expect(screen.queryByRole('menuitem', { name: '删除工作' })).toBeNull()
  expect(screen.queryByRole('button', { name: '编辑内容' })).toBeNull()
  expect(screen.queryByRole('button', { name: '记录新进展' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '全部附件 · 1' }))
  const materials = screen.getByRole('dialog', { name: '全部附件' })
  expect(await within(materials).findByRole('button', { name: '历史材料.txt' })).toBeTruthy()
  expect(within(materials).queryByRole('button', { name: '移除材料' })).toBeNull()
  expect(api).toHaveBeenCalledWith(
    '/work-items/work/materials?start=0&limit=20&revision=1',
    expect.anything(),
  )
})
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
  fireEvent.click(screen.getByRole('button', { name: '编辑内容' }))
  expect(await screen.findByText('尚未保存的方案')).toBeTruthy()
  expect(
    screen.getByRole('textbox', { name: '工作正文' }).querySelector('[data-work-material]'),
  ).toBeNull()
  expect(
    within(screen.getByRole('region', { name: '内容材料' })).getByText('需求.txt'),
  ).toBeTruthy()
  const submittedDraft = vault.getSnapshot()['work:body:work'] as { key: string }
  fireEvent.click(screen.getByRole('button', { name: '保存内容' }))
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
  fireEvent.click(screen.getByRole('button', { name: '保存内容' }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(write).toHaveBeenCalledTimes(2)
  expect(vi.mocked(write).mock.calls[1]).toEqual(first)
  expect(vault.getSnapshot()['work:body:work']).toBeUndefined()
  expect(screen.queryByRole('button', { name: '移除 需求.txt' })).toBeNull()
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
  fireEvent.click(screen.getByRole('button', { name: '读取当前内容' }))
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
