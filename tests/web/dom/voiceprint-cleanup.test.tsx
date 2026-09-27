// @vitest-environment jsdom
import type { VoiceprintCleanupSummary } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, write } from '../../../apps/web/src/api/client'
import { DeleteMember } from '../../../apps/web/src/features/members/components/DeleteMember'
import { VoiceprintsPage } from '../../../apps/web/src/features/voiceprints/components/VoiceprintsPage'
import { createVault, deferred, dialogs, identity, TestWorkspace } from './helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))
const summary: VoiceprintCleanupSummary = {
  legacy: { members: 1, voiceprints: 2, recordings: 3 },
  pending: 0,
  failed: 0,
}
const list = {
  items: [
    {
      memberId: 'active',
      name: '保留成员',
      role: 'employee',
      active: true,
      state: 'ready',
      ready: true,
      speechSeconds: 60,
    },
  ],
}
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
})
afterEach(cleanup)
it('keeps the member library available when the independent cleanup lookup fails', async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith('/cleanup')) throw new Error('清理范围暂不可用')
    return list
  })
  render(
    <TestWorkspace vault={createVault()}>
      <VoiceprintsPage />
    </TestWorkspace>,
  )
  expect(await screen.findByText('保留成员')).toBeTruthy()
  expect(await screen.findByText('清理范围暂不可用')).toBeTruthy()
  expect(screen.getByRole('button', { name: '替换录音' })).toBeTruthy()
})
it('refreshes destructive scope at confirmation and supports retry after a cleanup failure', async () => {
  let previews = 0
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith('/cleanup')
      ? { ...summary, legacy: { ...summary.legacy, voiceprints: ++previews === 1 ? 2 : 4 } }
      : list,
  )
  const request = deferred<VoiceprintCleanupSummary>()
  vi.mocked(write)
    .mockReturnValueOnce(request.promise)
    .mockResolvedValueOnce({ ...summary, legacy: { members: 0, voiceprints: 0, recordings: 0 } })
  render(
    <TestWorkspace vault={createVault()}>
      <VoiceprintsPage />
    </TestWorkspace>,
  )
  await screen.findByText(/遗留 2 份声纹/)
  fireEvent.click(screen.getByText('查看并清理'))
  expect(await screen.findByText(/1 位已删除成员的 4 份声纹和 3 份登记录音/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '确认清理' }))
  expect(write).toHaveBeenCalledExactlyOnceWith('/settings/voiceprints/cleanup', {})
  await act(async () => request.reject(new Error('文件暂时被占用')))
  expect(await screen.findByText('文件暂时被占用')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '确认清理' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByText('保留成员')).toBeTruthy()
  expect(write).toHaveBeenCalledTimes(2)
})
it('requires a fresh member deletion preview before enabling the destructive action', async () => {
  const preview = deferred<{ voiceprints: number; recordings: number }>(),
    deleted = vi.fn()
  vi.mocked(api).mockReturnValueOnce(preview.promise)
  vi.mocked(write).mockResolvedValueOnce({ ok: true, cleanupPending: 1 })
  render(
    <TestWorkspace vault={createVault()}>
      <DeleteMember member={identity.member} onClose={vi.fn()} onDeleted={deleted} />
    </TestWorkspace>,
  )
  const dialog = within(screen.getByRole('dialog'))
  expect((dialog.getByRole('button', { name: '删除账号' }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  await act(async () => preview.resolve({ voiceprints: 2, recordings: 3 }))
  expect(dialog.getByText(/同时删除 2 份声纹和 3 份登记录音/)).toBeTruthy()
  fireEvent.click(dialog.getByRole('button', { name: '删除账号' }))
  await waitFor(() => expect(deleted).toHaveBeenCalledOnce())
})
