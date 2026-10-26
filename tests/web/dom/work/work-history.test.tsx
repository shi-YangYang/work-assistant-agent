// @vitest-environment jsdom
import type { Work, WorkDocument } from '@paa/api-contracts'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it } from 'vitest'
import { WorkHistory } from '../../../../apps/web/src/features/work/components/detail/WorkHistory'
import { historyChanges, historyOrigin } from '../../../../apps/web/src/features/work/utils/history'

afterEach(cleanup)
const content = {
  title: '上线web',
  summary: '今天完成多次提交',
  status: 'in_progress' as const,
  blocker: '',
  nextStep: '',
}
const first = {
  id: 'r1',
  revision: 1,
  origin: 'manual' as const,
  content,
  sourceIds: [],
  createdAt: '2026-09-28T12:00:00Z',
}
const second = {
  ...first,
  id: 'r2',
  revision: 2,
  origin: 'assistant_confirmed' as const,
  content: { ...content, dueDate: '2026-10-01' },
}
const third = {
  ...first,
  id: 'r3',
  revision: 3,
  content: { ...second.content, status: 'done' as const },
}

it('hides creation-only history and shows later changes without numbered editions', () => {
  const work: Work = {
    ...third.content,
    id: 'w',
    ownerId: 'owner',
    revision: 3,
    updatedAt: first.createdAt,
    history: [third, second, first],
  }
  const { rerender } = render(
    <MemoryRouter>
      <WorkHistory work={{ ...work, revision: 1, history: [first] }} />
    </MemoryRouter>,
  )
  expect(screen.queryByRole('region', { name: '修改记录' })).toBeNull()
  expect(screen.queryByRole('link', { name: '查看当时内容' })).toBeNull()
  rerender(
    <MemoryRouter>
      <WorkHistory work={work} />
    </MemoryRouter>,
  )
  expect(screen.getByRole('region', { name: '修改记录' })).toBeTruthy()
  expect(screen.getAllByText('今天完成多次提交')).toHaveLength(1)
  expect(screen.getByText(/助手更新 · 已确认/)).toBeTruthy()
  expect(screen.getByText(/手动创建/)).toBeTruthy()
  expect(screen.getAllByText('2026-10-01')[0]).toBeTruthy()
  expect(screen.getByText('已完成')).toBeTruthy()
  expect(screen.queryByText(/第 3 版/)).toBeNull()
  expect(screen.getAllByRole('link', { name: '查看当时内容' })).toHaveLength(3)
})

it('includes clearing fields and never infers a diff across missing private history', () => {
  const cleared = {
    ...third,
    content: { ...third.content, dueDate: null, summary: '', blocker: '等待确认' },
  }
  expect(historyChanges(cleared, second)).toEqual(
    expect.arrayContaining([
      { key: 'dueDate', label: '截止日期', before: '2026-10-01', after: '未设置' },
      { key: 'summary', label: '工作说明', before: '今天完成多次提交', after: '未设置' },
      { key: 'blocker', label: '阻碍', before: '未设置', after: '等待确认' },
    ]),
  )
  expect(historyChanges(third, first)).toEqual([])
  expect(historyOrigin({ ...second, origin: undefined })).toBe('历史记录')
  expect(historyChanges({ ...second, content }, first)).toEqual([])
})

it('omits an empty initial body but records a later explicit clearing', () => {
  const empty: WorkDocument = { schemaVersion: 1, content: [] }
  const created = {
    ...first,
    content: { ...content, summary: '', body: empty, bodyText: '', materialIds: [] },
  }
  expect(historyChanges(created).map((change) => change.key)).not.toContain('body')
  expect(historyChanges(created).map((change) => change.key)).not.toContain('materials')
  const previous = {
    ...created,
    content: {
      ...created.content,
      bodyText: '旧正文',
      body: {
        schemaVersion: 1 as const,
        content: [{ type: 'paragraph', content: [{ type: 'text', text: '旧正文' }] }],
      },
    },
  }
  expect(historyChanges({ ...created, revision: 2 }, previous)).toContainEqual({
    key: 'body',
    label: '工作内容',
    before: undefined,
    after: '已清空正文',
  })
})

const paragraph = {
  type: 'paragraph',
  attrs: { id: 'paragraph-1' },
  content: [{ type: 'text', attrs: {}, text: '保留这段工作内容' }],
}
const material = { type: 'material', attrs: { id: 'material-1', materialId: 'file-1' } }
const document = (content: WorkDocument['content']): WorkDocument => ({ schemaVersion: 1, content })

it.each([
  {
    name: 'adding a material',
    before: { body: document([paragraph]), materialIds: [] },
    after: { body: document([paragraph, material]), materialIds: ['file-1'] },
    counts: ['0 个', '1 个'],
  },
  {
    name: 'removing a body reference while the file stays in the material library',
    before: { body: document([paragraph, material]), materialIds: ['file-1'] },
    after: { body: document([paragraph]), materialIds: ['file-1'] },
    counts: ['1 个', '0 个'],
  },
  {
    name: 'removing the file from the material library',
    before: { body: document([paragraph]), materialIds: ['file-1'] },
    after: { body: document([paragraph]), materialIds: [] },
    counts: ['1 个', '0 个'],
  },
  {
    name: 'adding a material with editor-generated IDs and an empty cursor paragraph',
    before: { body: document([paragraph]), materialIds: [] },
    after: {
      body: document([
        {
          type: 'paragraph',
          attrs: { id: 'editor-id' },
          content: [{ type: 'text', text: '保留这段工作内容' }],
        },
        material,
        { type: 'paragraph', attrs: { id: 'cursor' } },
      ]),
      materialIds: ['file-1'],
    },
    counts: ['0 个', '1 个'],
  },
])('reports only materials when $name', ({ before, after, counts }) => {
  const previous = { ...first, content: { ...content, ...before } }
  const current = { ...second, content: { ...content, ...after } }
  expect(historyChanges(current, previous)).toEqual([
    { key: 'materials', label: '材料', before: counts[0], after: counts[1] },
  ])
  render(
    <MemoryRouter>
      <WorkHistory
        work={{
          ...current.content,
          id: 'w',
          ownerId: 'owner',
          revision: 3,
          updatedAt: first.createdAt,
          history: [{ ...current, id: 'r3', revision: 3 }, current, previous],
        }}
      />
    </MemoryRouter>,
  )
  expect(screen.getAllByText('材料').length).toBeGreaterThan(0)
  expect(screen.queryByText('工作内容、材料已更新')).toBeNull()
})

it.each(['text', 'format'])('retains real %s changes when materials also change', (change) => {
  const previous = {
    ...first,
    content: { ...content, body: document([paragraph]), materialIds: [] },
  }
  const edited = {
    ...paragraph,
    content: [
      {
        type: 'text',
        text: change === 'text' ? '修改后的工作内容' : '保留这段工作内容',
        ...(change === 'format' ? { marks: [{ type: 'bold' }] } : {}),
      },
    ],
  }
  const current = {
    ...second,
    content: { ...content, body: document([edited, material]), materialIds: ['file-1'] },
  }
  expect(historyChanges(current, previous).map((entry) => entry.key)).toEqual(['body', 'materials'])
})

it('summarizes body edits without expanding saved prose', () => {
  const previous = {
    ...first,
    content: { ...content, body: document([paragraph]), bodyText: '保留这段工作内容' },
  }
  const current = {
    ...second,
    content: {
      ...previous.content,
      body: document([{ ...paragraph, content: [{ type: 'text', text: '当前正文不重复' }] }]),
      bodyText: '当前正文不重复',
    },
  }
  render(
    <MemoryRouter>
      <WorkHistory
        work={{
          ...current.content,
          id: 'w',
          ownerId: 'owner',
          revision: 2,
          updatedAt: first.createdAt,
          history: [current, previous],
        }}
      />
    </MemoryRouter>,
  )
  expect(screen.queryByText('当前正文不重复')).toBeNull()
  expect(screen.getAllByText('已修改正文').length).toBeGreaterThan(0)
  expect(screen.getAllByRole('link', { name: '查看当时内容' })[0].getAttribute('href')).toBe(
    '/work/w?revision=2',
  )
})
