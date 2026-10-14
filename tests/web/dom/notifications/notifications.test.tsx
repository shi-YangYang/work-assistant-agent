// @vitest-environment jsdom
import { createRef, StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NotificationsPage } from '../../../../apps/web/src/pages/NotificationsPage'
import { NotificationProvider } from '../../../../apps/web/src/features/notifications/components/NotificationProvider'
import { NotificationEntry } from '../../../../apps/web/src/features/notifications/components/NotificationEntry'
import { setCsrf } from '../../../../apps/web/src/api/client'
import { PetStage } from '../../../../apps/web/src/app/layout/pet/PetStage'
import { TestWorkspace, createVault, dialogs } from '../helpers'

let fetcher: ReturnType<typeof vi.fn>
beforeEach(() => {
  dialogs()
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  setCsrf('csrf', 'notifications')
  fetcher = vi.fn(
    async (url: string) =>
      new Response(
        JSON.stringify(
          url.includes('notification-summary')
            ? { remindersUnread: 2, announcementsUnread: 3, totalUnread: 5 }
            : { items: [], nextCursor: null, unread: 2 },
        ),
      ),
  )
  vi.stubGlobal('fetch', fetcher)
})
afterEach(() => {
  cleanup()
  setCsrf('')
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
function mount(path = '/notifications') {
  const vault = createVault()
  const router = createMemoryRouter(
    [
      {
        element: (
          <>
            <PetStage
              animate={false}
              navTriggerRef={createRef()}
              expandedNav={false}
              setExpandedNav={vi.fn()}
            />
            <Outlet />
          </>
        ),
        children: [
          { path: '/notifications', element: <NotificationsPage /> },
          { path: '/away', element: <p>Other page</p> },
        ],
      },
    ],
    { initialEntries: [path] },
  )
  render(
    <StrictMode>
      <TestWorkspace vault={vault}>
        <NotificationProvider scope="company:owner">
          <RouterProvider router={router} />
        </NotificationProvider>
      </TestWorkspace>
    </StrictMode>,
  )
  return router
}
it('shares the summary in the pet dialog and only refreshes when entering notifications', async () => {
  const router = mount('/away')
  const pet = await screen.findByRole('button', { name: 'Noria，5 条未读通知' })
  expect(screen.queryByRole('link', { name: /^通知/ })).toBeNull()
  fireEvent.click(pet)
  const dialog = screen.getByRole('dialog', { name: 'Noria' })
  const entry = within(dialog).getByRole('link', { name: '通知，5 条未读' })
  expect(within(dialog).getByRole('group', { name: '页面主题' })).toBeTruthy()
  expect(pet.getAttribute('aria-label')).toBe('Noria，5 条未读通知')
  expect(fetcher.mock.calls.filter(([url]) => url.includes('notification-summary'))).toHaveLength(1)
  fireEvent.click(entry)
  await waitFor(() => expect(router.state.location.pathname).toBe('/notifications'))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('button', { name: 'Noria，5 条未读通知' })).toBe(pet)
  expect(fetcher.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  // Entering the page retains its existing freshness check; opening the pet does not fetch.
  expect(fetcher.mock.calls.filter(([url]) => url.includes('notification-summary'))).toHaveLength(2)
})
it('defaults to unread reminders and restores explicit tabs, separate pagination and history', async () => {
  const router = mount()
  await waitFor(() => expect(router.state.location.search).toBe('?tab=reminders'))
  expect(screen.getByRole('tab', { name: '提醒 2' }).getAttribute('aria-selected')).toBe('true')
  fireEvent.click(screen.getByRole('tab', { name: '公告 3' }))
  expect(router.state.location.search).toBe('?tab=announcements')
  await act(() =>
    router.navigate('/notifications?tab=announcements&announcementPage=2&reminderPage=3'),
  )
  fireEvent.click(screen.getByRole('tab', { name: '提醒 2' }))
  expect(router.state.location.search).toContain('announcementPage=2&reminderPage=3')
  await act(() => router.navigate(-1))
  expect(screen.getByRole('tab', { name: '公告 3' }).getAttribute('aria-selected')).toBe('true')
  expect(fetcher.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  await act(() => router.navigate('/away'))
  await act(() => router.navigate('/notifications'))
  await waitFor(() => expect(router.state.location.search).toBe('?tab=announcements'))
})
it('marks a listed announcement read without navigation and clears its badge only after success', async () => {
  let unread = true
  let writes = 0
  let failRead!: (response: Response) => void
  fetcher.mockImplementation(async (url: string) => {
    if (url.endsWith('/read')) {
      writes++
      if (writes === 1)
        return new Promise<Response>((resolve) => {
          failRead = resolve
        })
      unread = false
      return new Response(JSON.stringify({ ok: true }))
    }
    if (url.includes('notification-summary'))
      return new Response(
        JSON.stringify({
          remindersUnread: 0,
          announcementsUnread: Number(unread),
          totalUnread: Number(unread),
        }),
      )
    if (!url.includes('/announcements?'))
      return new Response(JSON.stringify({ items: [], nextCursor: null, unread: 0 }))
    return new Response(
      JSON.stringify({
        items: [
          {
            id: 'one',
            title: '开会通知',
            summary: '请准时参加',
            state: 'published',
            revision: 3,
            unread,
            authorName: '管理员',
            publishedAt: '2026-10-13T00:00:00Z',
          },
        ],
        nextCursor: null,
      }),
    )
  })
  const router = mount('/notifications?tab=announcements')
  const read = await screen.findByRole('button', { name: '标为已读' })
  expect(screen.getByRole('tab', { name: '公告 1' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Noria，1 条未读通知' })).toBeTruthy()
  expect(writes).toBe(0)
  fireEvent.click(read)
  fireEvent.click(read)
  await waitFor(() => expect(writes).toBe(1))
  expect((read as HTMLButtonElement).disabled).toBe(true)
  await act(async () => failRead(new Response('{}', { status: 503 })))
  await screen.findByText('服务暂时不可用，请稍后重试。')
  expect(screen.getByLabelText('未读')).toBeTruthy()
  expect(screen.getByRole('tab', { name: '公告 1' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Noria，1 条未读通知' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '标为已读' }))
  await waitFor(() => {
    expect(screen.queryByLabelText('未读')).toBeNull()
    expect(screen.getByRole('tab', { name: '公告' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '标为已读' })).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('button', { name: 'Noria' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /未读通知/ })).toBeNull()
  })
  expect(router.state.location.pathname + router.state.location.search).toBe(
    '/notifications?tab=announcements',
  )
  const requests = fetcher.mock.calls.filter(([url]) => url.endsWith('/read'))
  expect(requests).toHaveLength(2)
  expect(
    requests.every(
      ([, options]) => options.method === 'POST' && JSON.parse(options.body).expectedRevision === 3,
    ),
  ).toBe(true)
})
it('has a single summary request shared by entry and page and pauses background polling', async () => {
  vi.useFakeTimers()
  let hidden = false
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  const router = createMemoryRouter(
    [
      {
        path: '*',
        element: (
          <>
            <NotificationEntry className="" labelClassName="" onNavigate={vi.fn()} />
            <NotificationsPage />
          </>
        ),
      },
    ],
    { initialEntries: ['/notifications?tab=announcements'] },
  )
  render(
    <TestWorkspace vault={createVault()}>
      <NotificationProvider scope="company:owner">
        <RouterProvider router={router} />
      </NotificationProvider>
    </TestWorkspace>,
  )
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
  expect(screen.getByRole('link', { name: '通知，5 条未读' })).toBeTruthy()
  const count = () =>
    fetcher.mock.calls.filter(([url]) => url.includes('notification-summary')).length
  expect(count()).toBe(1)
  hidden = true
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60000)
  })
  expect(count()).toBe(1)
  hidden = false
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(1)
  })
  expect(count()).toBe(2)
})

it('drops unread counts and late responses when the signed-in account changes', async () => {
  let resolveOld!: (response: Response) => void
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        resolveOld = resolve
      }),
  )
  fetcher.mockImplementation(
    async () =>
      new Response(JSON.stringify({ remindersUnread: 0, announcementsUnread: 1, totalUnread: 1 })),
  )
  const router = createMemoryRouter([
    {
      path: '*',
      element: <NotificationEntry className="" labelClassName="" onNavigate={vi.fn()} />,
    },
  ])
  const view = render(
    <NotificationProvider key="old" scope="old">
      <RouterProvider router={router} />
    </NotificationProvider>,
  )
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  act(() => setCsrf('new-csrf', 'new-account'))
  view.rerender(
    <NotificationProvider key="new" scope="new">
      <RouterProvider router={router} />
    </NotificationProvider>,
  )
  await screen.findByRole('link', { name: '通知，1 条未读' })
  await act(async () =>
    resolveOld(
      new Response(
        JSON.stringify({ remindersUnread: 90, announcementsUnread: 9, totalUnread: 99 }),
      ),
    ),
  )
  expect(screen.getByRole('link', { name: '通知，1 条未读' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: /99 条未读/ })).toBeNull()
})
