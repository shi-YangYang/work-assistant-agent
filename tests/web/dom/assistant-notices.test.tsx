// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Shell } from '../../../apps/web/src/app/Shell'
import { createVault, dialogs, identity } from './helpers'

const conversation = {
  id: 'chat',
  title: '提示验证',
  revision: 1,
  personaId: 'professional',
  executionMode: 'auto',
  fullAccessConfirmed: false,
}
let disconnected = false
function response(url: RequestInfo | URL) {
  const path = String(url)
  const data = path.endsWith('/conversations/chat')
    ? conversation
    : path.endsWith('/active-job')
      ? { job: null }
      : path.endsWith('/context-usage')
        ? { contextUsage: null }
        : { items: [], nextCursor: null, unread: 0 }
  return new Response(JSON.stringify(data))
}
function view(route = '/assistant/chat') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Shell identity={identity} vault={createVault()} onLogout={vi.fn()} />
    </MemoryRouter>,
  )
}
beforeEach(() => {
  dialogs()
  disconnected = false
  sessionStorage.clear()
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL) => {
      if (disconnected) throw new TypeError('Failed to fetch')
      return response(url)
    }),
  )
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('shows one assistant banner when sending and refreshing both fail, while preserving the draft', async () => {
  view()
  const input = await screen.findByRole('textbox', { name: '工作消息' })
  fireEvent.change(input, { target: { value: '断网时保留的草稿' } })
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '发送' }).hasAttribute('disabled')).toBe(false),
  )
  disconnected = true
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await screen.findByRole('button', { name: '原样重试，确认结果' })
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  await waitFor(() =>
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/conversations/chat'))
        .length,
    ).toBeGreaterThan(1),
  )
  expect(screen.getAllByText('无法连接服务，请检查网络后重试。')).toHaveLength(1)
  const notice = screen.getByRole('region', { name: '工作助手提示' })
  expect(within(notice).getAllByRole('alert')).toHaveLength(1)
  expect(notice.previousElementSibling?.tagName).toBe('HEADER')
  expect(within(notice).getByText(/原消息的提交结果尚未确认/)).toBeTruthy()
  expect(input.closest('[data-dragging]')?.querySelector('[role="alert"]')).toBeNull()
  expect((input as HTMLTextAreaElement).value).toBe('断网时保留的草稿')
})

it('shows and clears a single offline notice in a new empty conversation', async () => {
  view('/assistant?new=1')
  await screen.findByRole('textbox', { name: '工作消息' })
  await act(async () => window.dispatchEvent(new Event('offline')))
  const notice = screen.getByRole('region', { name: '工作助手提示' })
  expect(within(notice).getByText(/网络可能已断开/)).toBeTruthy()
  expect(screen.getAllByText(/网络可能已断开/)).toHaveLength(1)
  await act(async () => window.dispatchEvent(new Event('online')))
  expect(screen.queryByRole('region', { name: '工作助手提示' })).toBeNull()
})

it('one retry recovers failed page resources and removes the banner without resending messages', async () => {
  view()
  await screen.findByRole('textbox', { name: '工作消息' })
  disconnected = true
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  const notice = await screen.findByRole('region', { name: '工作助手提示' })
  await waitFor(() =>
    expect(screen.getAllByText('无法连接服务，请检查网络后重试。')).toHaveLength(1),
  )
  disconnected = false
  fireEvent.click(within(notice).getByRole('button', { name: '重试' }))
  await waitFor(() => expect(screen.queryByRole('region', { name: '工作助手提示' })).toBeNull())
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url) === '/api/v1/messages')).toBe(
    false,
  )
})

it('places a server rejection above the chat and keeps the editable draft', async () => {
  view('/assistant?new=1')
  const input = await screen.findByRole('textbox', { name: '工作消息' })
  vi.mocked(fetch).mockImplementation(async (url) =>
    String(url) === '/api/v1/messages'
      ? new Response(JSON.stringify({ code: 'validation', message: '请检查消息内容' }), {
          status: 422,
        })
      : response(url),
  )
  fireEvent.change(input, { target: { value: '被拒绝的消息' } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  const notice = await screen.findByRole('region', { name: '工作助手提示' })
  expect(within(notice).getByRole('alert')).toBeTruthy()
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect((input as HTMLTextAreaElement).readOnly).toBe(false)
  expect((input as HTMLTextAreaElement).value).toBe('被拒绝的消息')
})

it('uses the shared page notice for offline status on other pages', async () => {
  view('/work')
  await screen.findByRole('heading', { name: '我的工作' })
  await act(async () => window.dispatchEvent(new Event('offline')))
  expect(screen.getAllByText(/网络可能已断开/)).toHaveLength(1)
  expect(within(screen.getByRole('region', { name: '页面提示' })).getByRole('alert')).toBeTruthy()
  expect(screen.queryByRole('region', { name: '工作助手提示' })).toBeNull()
})
