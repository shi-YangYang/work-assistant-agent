// @vitest-environment jsdom
import type { Work, WorkDocument } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError, api, write } from '@web/api/client'
import { WorkContent } from '@web/features/work/components/content/WorkContent'
import { WorkRichText } from '@web/features/work/components/content/WorkRichText'
import { documentText } from '@web/features/work/utils/document'
import { historyChanges } from '@web/features/work/utils/history'
import { workChangeText } from '@web/features/assistant/utils/work-action-preview'
import { createVault, deferred, dialogs, TestWorkspace } from '../helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('@web/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))
const body = (checked = false): WorkDocument => ({
  schemaVersion: 1,
  content: [
    {
      type: 'taskList',
      attrs: { id: 'list' },
      content: [
        {
          type: 'taskItem',
          attrs: { id: 'one', checked },
          content: [{ type: 'paragraph', content: [{ type: 'text', text: '打印简历' }] }],
        },
        {
          type: 'taskItem',
          attrs: { id: 'two', checked: false },
          content: [{ type: 'paragraph', content: [{ type: 'text', text: '审核后交负责人确认' }] }],
        },
      ],
    },
    {
      type: 'paragraph',
      attrs: { id: 'note' },
      content: [{ type: 'text', text: '备注：打印机故障' }],
    },
  ],
})
const work: Work = {
  id: 'work',
  ownerId: 'owner',
  title: '今日待办',
  summary: '',
  status: 'in_progress',
  blocker: '',
  nextStep: '',
  revision: 1,
  updatedAt: '2026-10-12T01:00:00Z',
  body: body(),
  materialIds: [],
}
const view = (props: Partial<React.ComponentProps<typeof WorkContent>> = {}) =>
  render(
    <MemoryRouter>
      <TestWorkspace vault={createVault()}>
        <WorkContent work={work} own saved={vi.fn()} {...props} />
      </TestWorkspace>
    </MemoryRouter>,
  )
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  vi.mocked(api).mockResolvedValue(work)
})
afterEach(cleanup)

it('saves the exact item once and keeps the text node/focus without reloading while pending', async () => {
  const request = deferred<{ work: Work; materialIds: string[] }>()
  vi.mocked(write).mockReturnValue(request.promise)
  const saved = vi.fn()
  view({ saved })
  const checkbox = screen.getByRole('checkbox', { name: '打印简历' }) as HTMLInputElement
  const text = screen.getByText('备注：打印机故障')
  checkbox.focus()
  fireEvent.click(checkbox)
  expect(write).toHaveBeenCalledWith(
    '/work-items/work',
    { expectedRevision: 1, bodyEdits: [{ action: 'set_checked', itemId: 'one', checked: true }] },
    'PATCH',
    expect.any(String),
  )
  expect(screen.getByRole('status').textContent).toBe('正在保存清单…')
  expect(checkbox.disabled).toBe(true)
  fireEvent.click(checkbox)
  expect(write).toHaveBeenCalledOnce()
  await act(async () =>
    request.resolve({ work: { ...work, body: body(true), revision: 2 }, materialIds: [] }),
  )
  await waitFor(() => expect(checkbox.checked).toBe(true))
  expect(screen.getByText('备注：打印机故障')).toBe(text)
  expect(screen.getByRole('checkbox', { name: '打印简历' })).toBe(checkbox)
  expect(saved).toHaveBeenCalledOnce()
  expect(checkbox.disabled).toBe(false)
  vi.mocked(write).mockResolvedValue({ work: { ...work, revision: 3 }, materialIds: [] })
  fireEvent.click(checkbox)
  await waitFor(() => expect(checkbox.checked).toBe(false))
  expect(vi.mocked(write).mock.calls[1][1]).toEqual({
    expectedRevision: 2,
    bodyEdits: [{ action: 'set_checked', itemId: 'one', checked: false }],
  })
})

it('retains confirmed state on failure and refreshes explicitly after a conflict', async () => {
  const saved = vi.fn()
  vi.mocked(write).mockRejectedValue(new ApiError(409, 'conflict', '工作版本已变化'))
  view({ saved })
  fireEvent.click(screen.getByRole('checkbox', { name: '打印简历' }))
  await screen.findByText('工作版本已变化')
  expect((screen.getByRole('checkbox', { name: '打印简历' }) as HTMLInputElement).checked).toBe(
    false,
  )
  expect(write).toHaveBeenCalledOnce()
  expect(saved).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '读取最新版本' }))
  expect(saved).toHaveBeenCalledOnce()
})

it.each([{ own: false }, { work: { ...work, historical: true } }])(
  'makes other owners and historical versions readonly',
  (props) => {
    view(props)
    const checkbox = screen.getByRole('checkbox', { name: '打印简历' }) as HTMLInputElement
    expect(checkbox.disabled).toBe(true)
    fireEvent.click(checkbox)
    expect(write).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: '编辑内容' })).toBeNull()
  },
)

it('edits checkboxes only in the content draft until Save content', async () => {
  vi.mocked(write).mockResolvedValue({ work: { ...work, body: body(true), revision: 2 } })
  view()
  fireEvent.click(screen.getByRole('button', { name: '编辑内容' }))
  fireEvent.click(screen.getByRole('checkbox', { name: '打印简历' }))
  expect(write).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '保存内容' }))
  await waitFor(() => expect(write).toHaveBeenCalledOnce())
  const payload = vi.mocked(write).mock.calls[0][1] as { body: WorkDocument }
  expect(payload.body.content[0].content?.[0].attrs).toMatchObject({ id: 'one', checked: true })
  expect(documentText(payload.body)).toContain('☑ 打印简历\n☐ 审核后交负责人确认')
})

it('gives newly edited checklist items an identity without rewriting existing identities', async () => {
  const change = vi.fn()
  const document = body()
  document.content[0].content?.push({
    type: 'taskItem',
    attrs: { checked: false },
    content: [{ type: 'paragraph', content: [{ type: 'text', text: '新事项' }] }],
  })
  render(<WorkRichText body={document} change={change} />)
  fireEvent.click(screen.getByRole('checkbox', { name: '新事项' }))
  await waitFor(() => expect(change).toHaveBeenCalled())
  const updated = change.mock.calls.at(-1)![0] as WorkDocument
  const items = updated.content[0].content!
  expect(items[0].attrs?.id).toBe('one')
  expect(items[2].attrs?.id).toEqual(expect.any(String))
  expect(items[2].attrs?.id).not.toBe('one')
})

it('describes real checklist state changes in history and confirmation', () => {
  const first = {
    id: 'v1',
    revision: 1,
    content: { ...work, body: body() },
    createdAt: work.updatedAt,
    sourceIds: [],
  }
  const second = { ...first, id: 'v2', revision: 2, content: { ...work, body: body(true) } }
  expect(historyChanges(second, first)).toEqual([
    { key: 'check:one', label: '打印简历', before: '未完成', after: '已完成' },
  ])
  expect(
    workChangeText('bodyEdits', [
      {
        action: 'set_checked',
        itemId: 'one',
        text: '打印简历',
        beforeChecked: false,
        checked: true,
      },
    ]),
  ).toBe('1. 打印简历：未完成 → 已完成')
})
