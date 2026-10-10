// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, write } from '../../../apps/web/src/api/client'
import { SupportPage } from '../../../apps/web/src/features/feedback/components/SupportPage'
import { createVault, deferred, dialogs, identity, TestWorkspace } from './helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))

beforeEach(() => {
  dialogs()
  vi.resetAllMocks()
  vi.mocked(api).mockResolvedValue({ items: [], nextCursor: null })
})
afterEach(cleanup)

function show(role: 'employee' | 'admin' = 'employee', path = '/settings/support') {
  const account = { ...identity, member: { ...identity.member, role } }
  const vault = createVault(account)
  render(
    <MemoryRouter initialEntries={[path]}>
      <TestWorkspace vault={vault} account={account}>
        <SupportPage />
      </TestWorkspace>
    </MemoryRouter>,
  )
  return vault
}

it.each([
  ['employee', 'mine'],
  ['admin', 'all'],
] as const)(
  'preserves the draft while switching tabs and queries %s records with scope=%s',
  async (role, scope) => {
    show(role)
    expect(api).not.toHaveBeenCalled()
    fireEvent.change(screen.getByRole('textbox', { name: '问题描述' }), {
      target: { value: '切换页面时出现错误' },
    })
    fireEvent.keyDown(screen.getByRole('tab', { name: '提交反馈' }), { key: 'ArrowRight' })
    await screen.findByText('暂无反馈')
    expect(document.activeElement).toBe(screen.getByRole('tab', { name: '反馈记录' }))
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(api).toHaveBeenLastCalledWith(
      `/support-feedback?scope=${scope}&limit=20`,
      expect.anything(),
    )
    fireEvent.change(screen.getByLabelText('处理状态'), { target: { value: 'resolved' } })
    await waitFor(() =>
      expect(api).toHaveBeenLastCalledWith(
        `/support-feedback?scope=${scope}&state=resolved&limit=20`,
        expect.anything(),
      ),
    )
    fireEvent.click(screen.getByRole('tab', { name: '提交反馈' }))
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('切换页面时出现错误')
    expect(screen.queryByLabelText('处理状态')).toBeNull()
  },
)

it('retains failed submissions for an idempotent retry and opens unfiltered records after success', async () => {
  const vault = show('employee', '/settings/support?tab=submit&state=resolved&after=20')
  const pending = deferred<unknown>()
  vi.mocked(write).mockReturnValueOnce(pending.promise)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '提交后没有响应' } })
  fireEvent.click(screen.getByRole('button', { name: '提交反馈' }))
  expect((screen.getByRole('tab', { name: '反馈记录' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => pending.reject(new Error('网络中断')))
  expect(screen.getByRole('alert').textContent).toContain('网络中断')
  const firstRequest = vi.mocked(write).mock.calls[0]
  expect(firstRequest[1]).toMatchObject({
    description: '提交后没有响应',
    diagnostics: { category: 'unknown' },
  })
  vi.mocked(write).mockResolvedValueOnce({ id: 'saved-feedback' })
  fireEvent.click(screen.getByRole('button', { name: '原样重试，确认提交' }))
  await screen.findByText('暂无反馈')
  expect(vi.mocked(write).mock.calls[1]).toEqual(firstRequest)
  expect(screen.getByRole('tab', { name: '反馈记录' }).getAttribute('aria-selected')).toBe('true')
  expect(api).toHaveBeenLastCalledWith('/support-feedback?scope=mine&limit=20', expect.anything())
  expect(vault.getSnapshot().support).toBeUndefined()
})

it('opens old filtered record links while keeping the scope determined by the current role', async () => {
  show('employee', '/settings/support?scope=all&state=pending')
  await screen.findByText('暂无符合条件的反馈')
  expect(screen.getByRole('tab', { name: '反馈记录' }).getAttribute('aria-selected')).toBe('true')
  expect(api).toHaveBeenLastCalledWith(
    '/support-feedback?scope=mine&state=pending&limit=20',
    expect.anything(),
  )
})
