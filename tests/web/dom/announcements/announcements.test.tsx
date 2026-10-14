// @vitest-environment jsdom
import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AnnouncementDetail } from '../../../../apps/web/src/features/announcements/components/AnnouncementDetail'
import { AnnouncementEditor } from '../../../../apps/web/src/features/announcements/components/AnnouncementEditor'
import { AnnouncementsList } from '../../../../apps/web/src/features/announcements/components/AnnouncementsList'
import { AnnouncementManagementPage } from '../../../../apps/web/src/features/announcements/components/AnnouncementManagementPage'
import { setCsrf } from '../../../../apps/web/src/api/client'
import { TestWorkspace, createVault, deferred, dialogs, identity } from '../helpers'

const item = {
  id: 'one',
  title: '开会通知',
  markdown: '# 内容\n请准时参加',
  state: 'published',
  revision: 1,
  unread: true,
  authorName: '管理员',
  editorName: '管理员',
  publishedAt: '2026-10-13T00:00:00Z',
  updatedAt: '2026-10-13T00:00:00Z',
  withdrawnAt: null,
}
const admin = { ...identity, member: { ...identity.member, role: 'admin' as const } }
let fetcher: ReturnType<typeof vi.fn>
beforeEach(() => {
  dialogs()
  setCsrf('csrf', 'test-announcements')
  fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes('/read')) return new Response(JSON.stringify({ ok: true }))
    if (url.includes('/announcements?'))
      return new Response(
        JSON.stringify({ items: [{ ...item, summary: '请准时参加' }], nextCursor: null }),
      )
    if (options?.method === 'POST') return new Response(JSON.stringify(item), { status: 201 })
    return new Response(JSON.stringify(item))
  })
  vi.stubGlobal('fetch', fetcher)
})
afterEach(() => {
  cleanup()
  setCsrf('')
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
function mount(path: string, management = false) {
  const vault = createVault(management ? admin : identity)
  const router = createMemoryRouter(
    [
      { path: '/notifications', element: <AnnouncementsList /> },
      { path: '/notifications/announcements/:id', element: <AnnouncementDetail /> },
      { path: '/announcement-management', element: <AnnouncementManagementPage /> },
      { path: '/announcement-management/:id', element: <AnnouncementDetail management /> },
      { path: '/announcement-management/:id/edit', element: <AnnouncementEditor /> },
      { path: '/announcement-management/new', element: <AnnouncementEditor /> },
      { path: '/away', element: <p>其他页面</p> },
    ],
    { initialEntries: [path] },
  )
  render(
    <StrictMode>
      <TestWorkspace vault={vault} account={management ? admin : identity}>
        <RouterProvider router={router} />
      </TestWorkspace>
    </StrictMode>,
  )
  return { router, vault }
}
it('marks only a rendered reading detail once, including StrictMode, and retains list return URL', async () => {
  const changed = vi.fn()
  window.addEventListener('paa-notifications-changed', changed)
  const { router } = mount('/notifications?tab=announcements&announcementPage=2')
  fireEvent.click(await screen.findByRole('link', { name: /开会通知/ }))
  await screen.findByRole('heading', { name: '开会通知' })
  await waitFor(() =>
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/read'))).toHaveLength(1),
  )
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('link', { name: /返回通知/ }))
  expect(router.state.location.search).toBe('?tab=announcements&announcementPage=2')
  window.removeEventListener('paa-notifications-changed', changed)
})
it('management previews and editors never mark personal notices read', async () => {
  const { router } = mount('/announcement-management/one', true)
  await screen.findByRole('heading', { name: '开会通知' })
  expect(screen.getByRole('button', { name: '删除' })).toBeTruthy()
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/read'))).toBe(false)
  await act(() => router.navigate('/announcement-management/one/edit'))
  await screen.findByRole('textbox', { name: '公告正文' })
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/read'))).toBe(false)
})
it('confirms deletion, keeps its retry key after failure and returns to the management list', async () => {
  let deletes = 0
  fetcher.mockImplementation(async (url: string, options?: RequestInit) => {
    if (options?.method === 'DELETE') {
      deletes++
      return deletes === 1
        ? new Response('{}', { status: 503 })
        : new Response(JSON.stringify({ ok: true }))
    }
    if (url.includes('/announcements?'))
      return new Response(JSON.stringify({ items: [], nextCursor: null }))
    return new Response(JSON.stringify(item))
  })
  const confirm = vi.spyOn(window, 'confirm')
  const changed = vi.spyOn(window, 'dispatchEvent')
  const { router } = mount('/announcement-management/one', true)
  fireEvent.click(await screen.findByRole('button', { name: '删除' }))
  let dialog = screen.getByRole('dialog', { name: '删除公告' })
  expect(within(dialog).getByText(/开会通知.*无法恢复/)).toBeTruthy()
  fireEvent.click(within(dialog).getByRole('button', { name: '取消' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(deletes).toBe(0)
  fireEvent.click(screen.getByRole('button', { name: '删除' }))
  dialog = screen.getByRole('dialog', { name: '删除公告' })
  fireEvent.click(within(dialog).getByRole('button', { name: '删除' }))
  await screen.findByText('服务暂时不可用，请稍后重试。')
  expect(router.state.location.pathname).toBe('/announcement-management/one')
  fireEvent.click(within(dialog).getByRole('button', { name: '删除' }))
  await screen.findByRole('heading', { name: '公告管理' })
  expect(router.state.location.pathname).toBe('/announcement-management')
  expect(screen.queryByRole('combobox', { name: '公告状态' })).toBeNull()
  expect(
    changed.mock.calls.filter(([event]) => event.type === 'paa-notifications-changed'),
  ).toHaveLength(1)
  const calls = fetcher.mock.calls.filter(([, options]) => options?.method === 'DELETE')
  expect(calls).toHaveLength(2)
  expect(calls[0][0]).toMatch(/\/announcements\/one$/)
  expect(JSON.parse(calls[0][1].body)).toEqual({ expectedRevision: 1 })
  expect((calls[0][1].headers as Headers).get('Idempotency-Key')).toBeTruthy()
  expect((calls[0][1].headers as Headers).get('Idempotency-Key')).toBe(
    (calls[1][1].headers as Headers).get('Idempotency-Key'),
  )
  expect(confirm).not.toHaveBeenCalled()
})
it('deletes directly from the list and holds the dialog while submitting without duplicate requests', async () => {
  const response = deferred<Response>()
  let removed = false
  fetcher.mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'DELETE') {
      await response.promise
      removed = true
      return new Response(JSON.stringify({ ok: true }))
    }
    return new Response(
      JSON.stringify({
        items: removed ? [] : [{ ...item, summary: '请准时参加' }],
        nextCursor: null,
      }),
    )
  })
  const { router } = mount('/announcement-management?page=2', true)
  fireEvent.click(await screen.findByRole('button', { name: '删除' }))
  const dialog = screen.getByRole('dialog', { name: '删除公告' })
  expect(router.state.location.pathname).toBe('/announcement-management')
  expect(fetcher.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false)
  const submit = within(dialog).getByRole('button', { name: '删除' })
  fireEvent.click(submit)
  fireEvent.click(submit)
  fireEvent(dialog, new Event('cancel', { cancelable: true }))
  fireEvent.click(dialog)
  expect(screen.getByRole('dialog', { name: '删除公告' })).toBe(dialog)
  expect((within(dialog).getByRole('button', { name: '关闭' }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  expect((within(dialog).getByRole('button', { name: '取消' }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  await waitFor(() =>
    expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'DELETE')).toHaveLength(
      1,
    ),
  )
  expect(screen.getByRole('link', { name: /开会通知/ })).toBeTruthy()
  await act(async () => response.resolve(new Response('{}')))
  await screen.findByRole('heading', { name: '暂无公告' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(router.state.location.search).toBe('?page=1')
})
it('requires rechecking a changed announcement before deleting a new revision', async () => {
  let revision = 1
  fetcher.mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'DELETE') {
      revision = 2
      return new Response('{}', { status: 409 })
    }
    return new Response(
      JSON.stringify({ items: [{ ...item, revision, summary: '请准时参加' }], nextCursor: null }),
    )
  })
  mount('/announcement-management', true)
  fireEvent.click(await screen.findByRole('button', { name: '删除' }))
  const dialog = screen.getByRole('dialog', { name: '删除公告' })
  fireEvent.click(within(dialog).getByRole('button', { name: '删除' }))
  await within(dialog).findByText('公告已更新，请关闭弹窗后重新查看再删除。')
  expect((within(dialog).getByRole('button', { name: '删除' }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'DELETE')).toHaveLength(1)
  fireEvent.click(within(dialog).getByRole('button', { name: '取消' }))
  await screen.findByText('已更新')
  expect(screen.getByRole('link', { name: /开会通知/ })).toBeTruthy()
})
it('keeps a failed publication and its idempotency key across leaving and returning', async () => {
  let writes = 0
  fetcher.mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      writes++
      return writes === 1
        ? new Response('{}', { status: 503 })
        : new Response(JSON.stringify(item), { status: 201 })
    }
    return new Response(JSON.stringify(item))
  })
  const { router } = mount('/announcement-management/new', true)
  fireEvent.change(await screen.findByRole('textbox', { name: '公告标题' }), {
    target: { value: '标题' },
  })
  fireEvent.change(screen.getByRole('textbox', { name: '公告正文' }), { target: { value: '正文' } })
  fireEvent.click(screen.getByRole('button', { name: '发布' }))
  await screen.findByText('服务暂时不可用，请稍后重试。')
  await act(() => router.navigate('/away'))
  await act(() => router.navigate('/announcement-management/new'))
  expect(
    ((await screen.findByRole('textbox', { name: '公告标题' })) as HTMLInputElement).value,
  ).toBe('标题')
  fireEvent.click(screen.getByRole('button', { name: '原样重试' }))
  await screen.findByRole('heading', { name: '开会通知' })
  const calls = fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')
  expect(calls).toHaveLength(2)
  expect((calls[0][1]?.headers as Headers).get('Idempotency-Key')).toBe(
    (calls[1][1]?.headers as Headers).get('Idempotency-Key'),
  )
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body)
})
it('uses safe Markdown for content and preview, never embeds images or dangerous links', async () => {
  fetcher.mockResolvedValue(
    new Response(
      JSON.stringify({
        ...item,
        markdown:
          '<script>alert(1)</script>\n\n![图片](https://example.com/x.png)\n\n[危险](javascript:alert)\n\n[安全](https://example.com)',
      }),
    ),
  )
  mount('/announcement-management/one', true)
  await screen.findByRole('heading', { name: '开会通知' })
  expect(document.querySelector('script,img')).toBeNull()
  expect(screen.queryByRole('link', { name: '危险' })).toBeNull()
  expect(screen.getByRole('link', { name: '安全' }).getAttribute('rel')).toContain('noopener')
})
it('keeps a conflicting edit until explicitly loading the latest revision', async () => {
  let revision = 1
  fetcher.mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'PATCH') {
      revision = 2
      return new Response(
        JSON.stringify({
          error: { code: 'revision_conflict', message: '内容已变化，请读取最新版本' },
        }),
        { status: 409 },
      )
    }
    return new Response(
      JSON.stringify({ ...item, revision, title: revision === 1 ? '开会通知' : '最新标题' }),
    )
  })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  mount('/announcement-management/one/edit', true)
  fireEvent.change(await screen.findByRole('textbox', { name: '公告标题' }), {
    target: { value: '我的草稿' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存修改' }))
  await screen.findByRole('button', { name: '读取最新版本' })
  expect((screen.getByRole('textbox', { name: '公告标题' }) as HTMLInputElement).value).toBe(
    '我的草稿',
  )
  fireEvent.click(screen.getByRole('button', { name: '读取最新版本' }))
  await waitFor(() =>
    expect((screen.getByRole('textbox', { name: '公告标题' }) as HTMLInputElement).value).toBe(
      '最新标题',
    ),
  )
})
