// @vitest-environment jsdom
import type { BusinessAction } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { BusinessActionCard } from '../../../apps/web/src/features/assistant/components/interactions/BusinessActionCard'
import { resolveBusinessAction } from '../../../apps/web/src/features/assistant/api/requests'
import { documentFromText } from '../../../apps/web/src/features/work/utils/document'
import { deferred } from './helpers'
vi.mock('@web/features/assistant/api/requests', () => ({ resolveBusinessAction: vi.fn() }))
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})
const action: BusinessAction = {
  id: 'action',
  messageId: 'message',
  action: 'update_work',
  label: '修改工作',
  confirmLabel: '确认修改',
  state: 'pending',
  revision: 2,
  createdAt: '2026-09-28T00:00:00Z',
  canConfirm: true,
  preview: {
    title: '网站上线',
    revision: 1,
    before: { dueDate: '2026-09-28' },
    changes: { dueDate: '2026-09-30' },
  },
}
it('renders actual change previews and action labels, replaces pending controls immediately, then resumes', async () => {
  const request = deferred<Awaited<ReturnType<typeof resolveBusinessAction>>>(),
    continued = vi.fn()
  vi.mocked(resolveBusinessAction).mockReturnValue(request.promise)
  render(
    <MemoryRouter>
      <BusinessActionCard action={action} refresh={vi.fn()} onContinuation={continued} />
    </MemoryRouter>,
  )
  expect(screen.getByText('原内容：2026-09-28')).toBeTruthy()
  expect(screen.getByText('2026-09-30')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '确认修改' }))
  expect(screen.queryByRole('button', { name: '确认修改' })).toBeNull()
  expect(screen.getByRole('status')).toBeTruthy()
  expect(resolveBusinessAction).toHaveBeenCalledWith(action, 'confirm', { expectedRevision: 2 })
  const continuation = { conversationId: 'conversation', messageId: 'continued', jobId: 'job' }
  await act(async () =>
    request.resolve({
      ...action,
      state: 'succeeded',
      revision: 3,
      canConfirm: false,
      continuation,
    }),
  )
  expect(continued).toHaveBeenCalledExactlyOnceWith(continuation)
  expect(screen.getByText('已完成')).toBeTruthy()
})
it('restores the same confirmation after network failure and never reports success', async () => {
  vi.mocked(resolveBusinessAction).mockRejectedValue(new Error('网络中断'))
  const continued = vi.fn()
  render(
    <MemoryRouter>
      <BusinessActionCard action={action} refresh={vi.fn()} onContinuation={continued} />
    </MemoryRouter>,
  )
  fireEvent.click(screen.getByRole('button', { name: '确认修改' }))
  await screen.findByText('网络中断')
  expect(screen.getByRole('button', { name: '确认修改' })).toBeTruthy()
  expect(continued).not.toHaveBeenCalled()
})
it('previews original and replacement body blocks, removed content, and appended content separately', () => {
  render(
    <MemoryRouter>
      <BusinessActionCard
        action={{
          ...action,
          preview: {
            title: '网站上线',
            revision: 1,
            changes: {
              bodyEdits: [
                {
                  action: 'replace',
                  blockId: 'plan',
                  before: documentFromText('先做桌面端').content,
                  blocks: documentFromText('先做移动端').content,
                },
                {
                  action: 'remove',
                  blockId: 'obsolete',
                  before: documentFromText('取消的旧方案').content,
                  blocks: [],
                },
                {
                  action: 'append',
                  before: [],
                  blocks: documentFromText('补充验收标准').content,
                },
              ],
            },
          },
        }}
        refresh={vi.fn()}
      />
    </MemoryRouter>,
  )
  expect(screen.getByText(/1\. 修改指定内容/).textContent).toBe(
    [
      '1. 修改指定内容\n原内容：\n先做桌面端\n修改为：\n先做移动端',
      '2. 删除指定内容\n原内容：\n取消的旧方案\n修改为：删除以上内容',
      '3. 追加内容\n新增内容：\n补充验收标准',
    ].join('\n\n'),
  )
  expect(screen.getByRole('button', { name: '确认修改' })).toBeTruthy()
})
