// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { StrictMode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setCsrf } from '../../../apps/web/src/api/client'
import { App } from '../../../apps/web/src/app/App'

vi.mock('../../../apps/web/src/app/Shell', () => ({ Shell: () => null }))

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

beforeEach(() => {
  setCsrf('')
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: true })),
  )
})
afterEach(() => {
  cleanup()
  setCsrf('')
  vi.unstubAllGlobals()
})

function mountLogin() {
  return render(
    <StrictMode>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </StrictMode>,
  )
}

it('keeps anonymous startup and untouched fields quiet, then validates on submission', async () => {
  const fetch = vi.fn(async (path: string) => {
    if (path === '/api/v1/auth/providers') return response({ dingtalk: false })
    return response({ error: { code: 'login_required' } }, 401)
  })
  vi.stubGlobal('fetch', fetch)
  const view = mountLogin()
  fireEvent.click(await screen.findByRole('button', { name: /直接登录/ }))
  const username = screen.getByLabelText('账号')
  const password = screen.getByLabelText('密码', { exact: true })
  expect(document.activeElement).toBe(username)
  expect(screen.queryByText('Aborted')).toBeNull()
  act(() => password.focus())
  fireEvent.click(screen.getByRole('button', { name: '显示密码' }))
  fireEvent.blur(password)
  expect(password.getAttribute('type')).toBe('text')
  expect(screen.queryByText('请输入账号')).toBeNull()
  expect(screen.queryByText('请输入密码')).toBeNull()
  expect(screen.queryByRole('alert')).toBeNull()

  fireEvent.click(screen.getByRole('button', { name: '登录', exact: true }))
  expect(screen.getByText('请输入账号')).toBeTruthy()
  expect(screen.getByText('请输入密码')).toBeTruthy()
  expect(document.activeElement).toBe(username)
  expect(fetch.mock.calls.some(([path]) => path === '/api/v1/auth/login')).toBe(false)
  fireEvent.change(username, { target: { value: 'example' } })
  fireEvent.change(password, { target: { value: 'incorrect' } })
  expect(screen.queryByText('请输入账号')).toBeNull()
  expect(screen.queryByText('请输入密码')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '登录', exact: true }))
  expect(await screen.findByText('账号或密码不正确，请重新输入。')).toBeTruthy()
  expect(screen.queryByText('Aborted')).toBeNull()
  expect(fetch.mock.calls.filter(([path]) => path === '/api/v1/auth/me')).toHaveLength(1)
  view.unmount()
})

it.each(['network', 'server'])(
  'opens the form automatically for a real %s failure during session discovery',
  async (failure) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (path: string) => {
        if (path === '/api/v1/auth/providers') return response({ dingtalk: false })
        if (failure === 'network') throw new TypeError('Failed to fetch')
        return response({}, 503)
      }),
    )
    mountLogin()
    expect(await screen.findByRole('button', { name: '合上书本' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /直接登录/ })).toBeNull()
    expect(screen.getByRole('alert').textContent).toBe(
      failure === 'network' ? '无法连接服务，请检查网络后重试。' : '服务暂时不可用，请稍后重试。',
    )
    expect(screen.queryByText('Aborted')).toBeNull()
  },
)
