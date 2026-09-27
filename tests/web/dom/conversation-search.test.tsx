// @vitest-environment jsdom
import type { Conversation, Page } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { readMoreConversations } from '../../../apps/web/src/features/assistant/api/requests'
import { useConversationSearch } from '../../../apps/web/src/features/assistant/hooks/useConversationSearch'
import { createVault, deferred, identity, TestWorkspace } from './helpers'
vi.mock('@web/features/assistant/api/requests', () => ({ readMoreConversations: vi.fn() }))
const page = (id: string, nextCursor: string | null = null): Page<Conversation> => ({
  items: [{ id, title: id } as Conversation],
  nextCursor,
})
function Picker() {
  const [open, setOpen] = useState(true)
  const search = useConversationSearch(open)
  return (
    <>
      <button onClick={() => setOpen(!open)}>切换弹层</button>
      <input
        aria-label="搜索"
        value={search.search}
        onChange={(event) => search.setSearch(event.target.value)}
      />
      {search.data?.items.map((item) => (
        <p key={item.id}>{item.title}</p>
      ))}
      {search.error && <p role="alert">{String(search.error)}</p>}
      <button onClick={search.refresh}>重试</button>
      <button
        disabled={search.loading || !search.data?.nextCursor}
        onClick={() => void search.loadMore()}
      >
        更多
      </button>
    </>
  )
}
beforeEach(() => vi.clearAllMocks())
afterEach(cleanup)
it('aborts old pagination and never mixes its late page into a new query', async () => {
  const older = deferred<Page<Conversation>>()
  vi.mocked(readMoreConversations).mockImplementation(async (q, cursor) =>
    cursor ? older.promise : page(q || '初始', 'cursor'),
  )
  render(
    <TestWorkspace vault={createVault()}>
      <Picker />
    </TestWorkspace>,
  )
  await screen.findByText('初始')
  fireEvent.click(screen.getByText('更多'))
  fireEvent.click(screen.getByText('更多'))
  const more = vi.mocked(readMoreConversations).mock.calls.find(([, cursor]) => !!cursor)!
  expect(vi.mocked(readMoreConversations).mock.calls.filter(([, cursor]) => !!cursor)).toHaveLength(
    1,
  )
  fireEvent.change(screen.getByLabelText('搜索'), { target: { value: '新搜索' } })
  await screen.findByText('新搜索')
  expect(more[2]?.aborted).toBe(true)
  await act(async () => older.resolve(page('过期分页', 'bad-cursor')))
  expect(screen.queryByText('过期分页')).toBeNull()
  fireEvent.click(screen.getByText('更多'))
  expect(readMoreConversations).toHaveBeenLastCalledWith(
    '新搜索',
    'cursor',
    expect.any(AbortSignal),
  )
})
it('cancels on close and account change, then retries a failed initial request', async () => {
  const pending = deferred<Page<Conversation>>(),
    vault = createVault()
  vi.mocked(readMoreConversations)
    .mockReturnValueOnce(pending.promise)
    .mockRejectedValueOnce(new Error('离线'))
    .mockResolvedValue(page('恢复后的会话'))
  const mounted = render(
    <TestWorkspace vault={vault}>
      <Picker />
    </TestWorkspace>,
  )
  const signal = vi.mocked(readMoreConversations).mock.calls[0][2]
  fireEvent.click(screen.getByText('切换弹层'))
  expect(signal?.aborted).toBe(true)
  await act(async () => pending.resolve(page('不应显示')))
  expect(screen.queryByText('不应显示')).toBeNull()
  fireEvent.click(screen.getByText('切换弹层'))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByText('重试'))
  await screen.findByText('恢复后的会话')
  const account = { ...identity, member: { ...identity.member, id: 'next' } }
  mounted.rerender(
    <TestWorkspace vault={vault} account={account}>
      <Picker />
    </TestWorkspace>,
  )
  await waitFor(() => expect(readMoreConversations).toHaveBeenCalledTimes(4))
})
