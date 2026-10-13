// @vitest-environment jsdom
import { StrictMode, useLayoutEffect } from 'react'
import type { Identity } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, Outlet, RouterProvider, useLocation } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AnnouncementsList } from '../../../../apps/web/src/features/announcements/components/AnnouncementsList'
import { AnnouncementDetail } from '../../../../apps/web/src/features/announcements/components/AnnouncementDetail'
import { setCsrf } from '../../../../apps/web/src/api/client'
import { clearQueryResources } from '../../../../apps/web/src/lib/query-resource'
import { TestWorkspace, createVault, deferred, identity } from '../helpers'

const item = {
  id: 'one',
  title: '公告一',
  summary: '摘要',
  markdown: '正文',
  state: 'published',
  revision: 1,
  authorName: '管理员',
  editorName: '管理员',
  unread: false,
  publishedAt: '2026-10-13T00:00:00Z',
  updatedAt: '2026-10-13T00:00:00Z',
  withdrawnAt: null,
}
const response = () => new Response(JSON.stringify({ items: [item], nextCursor: null }))
let nextList: ReturnType<typeof deferred<Response>> | undefined
beforeEach(() => {
  setCsrf('csrf', 'announcement-scroll')
  nextList = undefined
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url.includes('/announcements?')
        ? (nextList?.promise ?? response())
        : new Response(JSON.stringify(item)),
    ),
  )
})
afterEach(() => {
  cleanup()
  clearQueryResources()
  setCsrf('')
  vi.unstubAllGlobals()
})
function Shell() {
  const location = useLocation()
  // The shell's initial restoration runs before asynchronous list data arrives.
  useLayoutEffect(() => {
    const node = document.querySelector<HTMLElement>('[data-scroll-container]')
    if (node) node.scrollTop = 0
  }, [location.pathname, location.search])
  return <Outlet />
}
function scrollContainer(node: HTMLDivElement | null) {
  if (!node) return
  let top = 0
  Object.defineProperty(node, 'scrollTop', {
    configurable: true,
    get: () => top,
    set: (value: number) => {
      top = Math.min(value, node.querySelector('a strong') ? 2000 : 0)
    },
  })
}
function mount(management: boolean) {
  const path = management
    ? '/announcement-management?state=published&page=2'
    : '/notifications?tab=announcements&announcementPage=2&reminderPage=3'
  const vault = createVault()
  const router = createMemoryRouter(
    [
      {
        element: <Shell />,
        children: [
          {
            path: '/announcement-management',
            element: (
              <div ref={scrollContainer} data-scroll-container>
                <AnnouncementsList management />
              </div>
            ),
          },
          {
            path: '/notifications',
            element: (
              <div ref={scrollContainer} data-scroll-container>
                <AnnouncementsList />
              </div>
            ),
          },
          { path: '/announcement-management/:id', element: <AnnouncementDetail management /> },
          { path: '/notifications/announcements/:id', element: <AnnouncementDetail /> },
        ],
      },
    ],
    { initialEntries: [path] },
  )
  const workspace = (account: Identity) => (
    <StrictMode>
      <TestWorkspace vault={vault} account={account}>
        <RouterProvider router={router} />
      </TestWorkspace>
    </StrictMode>
  )
  const view = render(workspace(identity))
  return {
    path,
    router,
    vault,
    changeAccount: (account: Identity) => view.rerender(workspace(account)),
  }
}
async function leaveList(management: boolean) {
  const result = mount(management)
  await screen.findByRole('link', { name: /公告一/ })
  const node = document.querySelector<HTMLElement>('[data-scroll-container]')!
  node.scrollTop = 1800
  fireEvent.scroll(node)
  fireEvent.click(screen.getByRole('link', { name: /公告一/ }))
  await screen.findByRole('heading', { name: '公告一' })
  // Deterministically represent the list cache's 30-second idle eviction.
  clearQueryResources()
  nextList = deferred<Response>()
  return result
}
it.each([true, false])(
  'restores the loaded list once after eviction (management=%s)',
  async (management) => {
    const { router, path, vault } = await leaveList(management)
    expect(vault.getSnapshot()).toEqual({})
    fireEvent.click(screen.getByRole('link', { name: management ? '返回公告管理' : '返回通知' }))
    await screen.findByText('正在读取公告…')
    const node = document.querySelector<HTMLElement>('[data-scroll-container]')!
    expect(node.scrollTop).toBe(0)
    await act(async () => {
      nextList!.resolve(response())
    })
    await waitFor(() => expect(node.scrollTop).toBe(1800))
    expect(router.state.location.pathname + router.state.location.search).toBe(path)
    node.scrollTop = 350
    fireEvent.scroll(node)
    nextList = undefined
    await act(async () => {
      window.dispatchEvent(new Event('paa-notifications-changed'))
    })
    expect(node.scrollTop).toBe(350)
    expect(vault.getSnapshot()).toEqual({})
  },
)
it('respects user scrolling while the returning list is still loading', async () => {
  await leaveList(true)
  fireEvent.click(screen.getByRole('link', { name: '返回公告管理' }))
  await screen.findByText('正在读取公告…')
  const node = document.querySelector<HTMLElement>('[data-scroll-container]')!
  fireEvent.wheel(node, { deltaY: -100 })
  await act(async () => {
    nextList!.resolve(response())
  })
  expect(node.scrollTop).toBe(0)
})
it('does not restore a previous identity’s list position', async () => {
  const { vault, changeAccount } = await leaveList(false)
  const other = { ...identity, member: { ...identity.member, id: 'other' } }
  await act(() => {
    vault.resume(other)
    changeAccount(other)
  })
  fireEvent.click(screen.getByRole('link', { name: '返回通知' }))
  await screen.findByText('正在读取公告…')
  const node = document.querySelector<HTMLElement>('[data-scroll-container]')!
  await act(async () => {
    nextList!.resolve(response())
  })
  expect(node.scrollTop).toBe(0)
})
it('ignores departing list cleanup after a new login, even for the same account', async () => {
  const { router, path, vault } = mount(false)
  await screen.findByRole('link', { name: /公告一/ })
  const previous = document.querySelector<HTMLElement>('[data-scroll-container]')!
  previous.scrollTop = 1800
  fireEvent.scroll(previous)
  // Session invalidation precedes route teardown. The old effect's cleanup must
  // not repopulate the next session's navigation state.
  setCsrf('new-csrf', 'announcement-scroll')
  fireEvent.click(screen.getByRole('link', { name: /公告一/ }))
  await screen.findByRole('heading', { name: '公告一' })
  clearQueryResources()
  nextList = deferred<Response>()
  await act(() => router.navigate(path))
  await screen.findByText('正在读取公告…')
  await act(async () => nextList!.resolve(response()))
  expect(document.querySelector<HTMLElement>('[data-scroll-container]')!.scrollTop).toBe(0)
  expect(vault.getSnapshot()).toEqual({})
})
it('leaves genuine unsaved content intact while remembering navigation', async () => {
  const { router, path, vault } = await leaveList(true)
  const draft = { title: '未提交的公告', markdown: '不要丢失正文' }
  await act(() => vault.writer()('announcement:new', draft))
  await act(() => router.navigate(path))
  await screen.findByText('正在读取公告…')
  await act(async () => nextList!.resolve(response()))
  expect(document.querySelector<HTMLElement>('[data-scroll-container]')!.scrollTop).toBe(1800)
  expect(vault.getSnapshot()).toEqual({ 'announcement:new': draft })
})
