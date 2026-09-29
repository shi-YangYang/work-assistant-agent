// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode, useState } from 'react'
import { createMemoryRouter, MemoryRouter, RouterProvider, useNavigate } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../../apps/web/src/api/client'
import { Shell } from '../../../apps/web/src/app/layout/Shell'
import { ErrorNotice } from '../../../apps/web/src/components/feedback/ErrorNotice'
import {
  ErrorNoticeOutlet,
  ErrorNoticeScope,
} from '../../../apps/web/src/components/feedback/ErrorNoticeScope'
import { FormField } from '../../../apps/web/src/components/forms/FormField'
import { Modal } from '../../../apps/web/src/components/overlays/Modal'
import { ErrorDiagnostics, SupportLink } from '../../../apps/web/src/lib/support-link'
import { createVault, dialogs, identity } from './helpers'

const networkMessage = '无法连接服务，请检查网络后重试。'
beforeEach(() => {
  dialogs()
  sessionStorage.clear()
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  )
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function offline() {
  act(() =>
    window.dispatchEvent(new CustomEvent('paa-connection-error', { detail: networkMessage })),
  )
}

it('deduplicates network and page failures and retries every failed read once', () => {
  const first = vi.fn(),
    second = vi.fn()
  const view = render(
    <StrictMode>
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
        <ErrorNotice retry={first}>{new Error(networkMessage)}</ErrorNotice>
        <ErrorNotice retry={second}>{new Error(networkMessage)}</ErrorNotice>
      </ErrorNoticeScope>
    </StrictMode>,
  )
  offline()
  expect(screen.getAllByText(networkMessage)).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(first).toHaveBeenCalledTimes(1)
  expect(second).toHaveBeenCalledTimes(1)
  view.rerender(
    <StrictMode>
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
      </ErrorNoticeScope>
    </StrictMode>,
  )
  act(() => window.dispatchEvent(new Event('paa-request-connected')))
  expect(screen.queryByRole('alert')).toBeNull()
})

it('keeps a distinct unresolved error available after the latest failure clears', () => {
  function Page() {
    const [error, setError] = useState('保存失败')
    return (
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
        <ErrorNotice>列表读取失败</ErrorNotice>
        <ErrorNotice retry={() => setError('')}>{error}</ErrorNotice>
      </ErrorNoticeScope>
    )
  }
  render(<Page />)
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(screen.getByRole('alert').textContent).toContain('保存失败')
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(screen.getByRole('alert').textContent).toContain('列表读取失败')
})

it('puts dialog failures only in the foreground dialog and preserves field validation', () => {
  function Page() {
    const [open, setOpen] = useState(true)
    return (
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
        <ErrorNotice>页面暂时不可用</ErrorNotice>
        {open && (
          <Modal title="编辑成员" onClose={() => setOpen(false)}>
            <FormField label="姓名" error="请输入姓名" />
            <ErrorNotice>{new Error(networkMessage)}</ErrorNotice>
            <ErrorNotice>{new Error(networkMessage)}</ErrorNotice>
          </Modal>
        )}
      </ErrorNoticeScope>
    )
  }
  render(<Page />)
  offline()
  const dialog = screen.getByRole('dialog', { name: '编辑成员' })
  expect(screen.getAllByText(networkMessage)).toHaveLength(1)
  expect(within(dialog).getByRole('region', { name: '编辑成员提示' })).toBeTruthy()
  expect(screen.queryByRole('region', { name: '页面提示' })).toBeNull()
  expect(within(dialog).getByRole('textbox', { name: '姓名' }).getAttribute('aria-invalid')).toBe(
    'true',
  )
  expect(within(dialog).getByText('请输入姓名')).toBeTruthy()
  fireEvent.click(within(dialog).getByRole('button', { name: '关闭' }))
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(screen.getByRole('alert').textContent).toContain('页面暂时不可用')
})

it('gives a topbar dialog precedence over the assistant outlet and restores the assistant on close', () => {
  function Page() {
    const [open, setOpen] = useState(true)
    return (
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
        <ErrorNoticeScope priority={10}>
          <ErrorNoticeOutlet label="助手提示" />
          <ErrorNotice>聊天加载失败</ErrorNotice>
        </ErrorNoticeScope>
        {open && (
          <Modal title="通知" onClose={() => setOpen(false)}>
            <ErrorNotice>通知加载失败</ErrorNotice>
          </Modal>
        )}
      </ErrorNoticeScope>
    )
  }
  render(
    <StrictMode>
      <Page />
    </StrictMode>,
  )
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(within(screen.getByRole('dialog')).getByText('通知加载失败')).toBeTruthy()
  expect(screen.queryByText('聊天加载失败')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '关闭' }))
  expect(screen.getByRole('alert').textContent).toContain('聊天加载失败')
})

it('preserves cancellation, permission and the longest retry cooldown when failures are merged', () => {
  const retry = vi.fn()
  const view = render(
    <ErrorNoticeScope>
      <ErrorNoticeOutlet />
      <ErrorNotice retry={retry}>
        {new ApiError(429, 'limited', '请稍后重试', 'rate_limited', null, 30)}
      </ErrorNotice>
      <ErrorNotice retry={retry}>
        {new ApiError(429, 'limited', '请稍后重试', 'rate_limited', null, 5)}
      </ErrorNotice>
      <ErrorNotice>{new ApiError(0, 'cancelled', '', 'cancelled')}</ErrorNotice>
    </ErrorNoticeScope>,
  )
  expect(screen.getByRole('button', { name: '30 秒后重试' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  view.rerender(
    <ErrorNoticeScope>
      <ErrorNoticeOutlet />
      <ErrorNotice retry={retry}>
        {new ApiError(403, 'forbidden', '没有访问权限', 'forbidden')}
      </ErrorNotice>
    </ErrorNoticeScope>,
  )
  expect(screen.getByRole('alert').textContent).toBe('没有访问权限')
  expect(screen.queryByRole('button')).toBeNull()
  expect(retry).not.toHaveBeenCalled()
})

it('retains diagnostic actions from the error source without enabling them for other pages', () => {
  const view = render(
    <MemoryRouter>
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
        <ErrorDiagnostics.Provider value={true}>
          <SupportLink.Provider value="/settings/support">
            <ErrorNotice>助手请求失败</ErrorNotice>
          </SupportLink.Provider>
        </ErrorDiagnostics.Provider>
      </ErrorNoticeScope>
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: '问题反馈' }).getAttribute('href')).toBe(
    '/settings/support',
  )
  view.rerender(
    <MemoryRouter>
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
        <ErrorNotice>列表请求失败</ErrorNotice>
      </ErrorNoticeScope>
    </MemoryRouter>,
  )
  expect(screen.queryByRole('link')).toBeNull()
})

it.each([
  '/work',
  '/work/test',
  '/reports',
  '/reports/test',
  '/team',
  '/members',
  '/settings/account',
  '/settings/support',
  '/settings/rules',
  '/settings/models',
  '/settings/voiceprints',
  '/settings/login',
  '/settings/usage',
])('shows a single page notice for failed requests on %s', async (route) => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  const account =
    route === '/reports' || route.startsWith('/reports/')
      ? identity
      : { ...identity, member: { ...identity.member, role: 'admin' as const } }
  const router = createMemoryRouter(
    [
      {
        path: '*',
        element: <Shell identity={account} vault={createVault(account)} onLogout={vi.fn()} />,
      },
    ],
    { initialEntries: [route] },
  )
  render(<RouterProvider router={router} />)
  await waitFor(() => expect(screen.queryByText('正在加载页面')).toBeNull())
  await waitFor(() => expect(screen.getAllByText(networkMessage)).toHaveLength(1))
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(within(screen.getByRole('region', { name: '页面提示' })).getByRole('alert')).toBeTruthy()
})

it('cleans up old page errors on navigation and clears the offline fallback after recovery', async () => {
  let failed = true
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      if (failed) throw new TypeError('Failed to fetch')
      return new Response(JSON.stringify({ items: [], nextCursor: null }))
    }),
  )
  function App() {
    const navigate = useNavigate()
    return (
      <>
        <button
          onClick={() => {
            failed = false
            void navigate('/settings/appearance')
          }}
        >
          切换页面
        </button>
        <Shell identity={identity} vault={createVault()} onLogout={vi.fn()} />
      </>
    )
  }
  render(
    <MemoryRouter initialEntries={['/work']}>
      <App />
    </MemoryRouter>,
  )
  await screen.findByText(networkMessage)
  await screen.findByRole('button', { name: '重试' })
  fireEvent.click(screen.getByRole('button', { name: '切换页面' }))
  await screen.findByRole('heading', { name: '外观' })
  act(() => window.dispatchEvent(new Event('online')))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
})
