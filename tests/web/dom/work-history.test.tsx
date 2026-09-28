// @vitest-environment jsdom
import type { Work } from '@paa/api-contracts'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it } from 'vitest'
import { WorkHistory } from '../../../apps/web/src/features/work/components/WorkHistory'
import { historyChanges, historyOrigin } from '../../../apps/web/src/features/work/utils/history'

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

it('shows field changes and correct authorship without repeating unchanged summaries', () => {
  const work: Work = {
    ...third.content,
    id: 'w',
    ownerId: 'owner',
    revision: 3,
    updatedAt: first.createdAt,
    history: [third, second, first],
  }
  render(
    <MemoryRouter>
      <WorkHistory work={work} />
    </MemoryRouter>,
  )
  expect(screen.getAllByText('今天完成多次提交')).toHaveLength(1)
  expect(screen.getByText(/助手更新 · 已确认/)).toBeTruthy()
  expect(screen.getByText(/手动更新/)).toBeTruthy()
  expect(screen.getByText('2026-10-01')).toBeTruthy()
  expect(screen.getByText('已完成')).toBeTruthy()
  expect(screen.queryByRole('link')).toBeNull()
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
  expect(historyChanges(third, first).every((change) => change.before === undefined)).toBe(true)
  expect(historyOrigin({ ...second, origin: undefined })).toBe('历史记录')
  expect(historyChanges({ ...second, content }, first)).toEqual([])
})
