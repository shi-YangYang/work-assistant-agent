// @vitest-environment jsdom
import type { BusinessAction } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { BusinessActionCard } from '../../../apps/web/src/features/assistant/components/BusinessActionCard'
import { resolveBusinessAction } from '../../../apps/web/src/features/assistant/api/requests'
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
