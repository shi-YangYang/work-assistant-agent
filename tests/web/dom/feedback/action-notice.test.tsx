// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../../../apps/web/src/api/client'
import { ActionNotice } from '../../../../apps/web/src/components/feedback/ActionNotice'
import { ErrorNotice } from '../../../../apps/web/src/components/feedback/ErrorNotice'
import {
  ErrorNoticeOutlet,
  ErrorNoticeScope,
} from '../../../../apps/web/src/components/feedback/ErrorNoticeScope'
import { Modal } from '../../../../apps/web/src/components/overlays/Modal'
import { ErrorDiagnostics, SupportLink } from '../../../../apps/web/src/lib/support-link'
import { dialogs } from '../helpers'

beforeEach(() => {
  vi.useFakeTimers()
  dialogs()
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

it('dismisses outside the layout without changing caller error metadata or resetting on rerender', () => {
  const failure = new ApiError(422, 'invalid', '保存失败')
  failure.fieldErrors.title = '请输入标题'
  const view = render(<ActionNotice>{failure}</ActionNotice>)
  expect(view.container.querySelector('[role="alert"]')).toBeNull()
  act(() => vi.advanceTimersByTime(6000))
  view.rerender(<ActionNotice>{failure}</ActionNotice>)
  act(() => vi.advanceTimersByTime(4000))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(failure.fieldErrors.title).toBe('请输入标题')
  view.rerender(<ActionNotice>{new Error('保存失败')}</ActionNotice>)
  expect(screen.getByRole('alert')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '关闭提示' }))
  expect(screen.queryByRole('alert')).toBeNull()
})

it('pauses dismissal while reading with a pointer or keyboard and supports repeating string failures', () => {
  const view = render(<ActionNotice>操作失败</ActionNotice>)
  const toast = screen.getByRole('alert').parentElement!
  fireEvent.mouseEnter(toast)
  act(() => vi.advanceTimersByTime(20000))
  expect(screen.getByRole('alert')).toBeTruthy()
  fireEvent.focus(screen.getByRole('button', { name: '关闭提示' }))
  fireEvent.mouseLeave(toast)
  act(() => vi.advanceTimersByTime(20000))
  expect(screen.getByRole('alert')).toBeTruthy()
  fireEvent.blur(screen.getByRole('button', { name: '关闭提示' }), { relatedTarget: document.body })
  act(() => vi.advanceTimersByTime(10000))
  expect(screen.queryByRole('alert')).toBeNull()
  view.rerender(<ActionNotice>{''}</ActionNotice>)
  view.rerender(<ActionNotice>操作失败</ActionNotice>)
  expect(screen.getByRole('alert')).toBeTruthy()
})

it('merges matching actions without borrowing a read retry or hiding the unresolved load failure', () => {
  const refresh = vi.fn()
  render(
    <ErrorNoticeScope>
      <ErrorNoticeOutlet />
      <ErrorNotice retry={refresh}>请求失败</ErrorNotice>
      <ActionNotice>请求失败</ActionNotice>
      <ActionNotice>请求失败</ActionNotice>
    </ErrorNoticeScope>,
  )
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(screen.queryByRole('region', { name: '页面提示' })).toBeNull()
  expect(screen.queryByRole('button', { name: '重试' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '关闭提示' }))
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(within(screen.getByRole('region', { name: '页面提示' })).getByRole('alert')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(refresh).toHaveBeenCalledTimes(1)
})

it('keeps page loading failures outside the layout until recovery without an automatic dismissal', () => {
  function Page() {
    const [error, setError] = useState('列表加载失败')
    return (
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
        <h1>我的工作</h1>
        <ErrorNotice retry={() => setError('')}>{error}</ErrorNotice>
      </ErrorNoticeScope>
    )
  }
  const { container } = render(<Page />)
  expect(container.querySelector('[role="region"]')).toBeNull()
  expect(container.querySelector('[role="alert"]')).toBeNull()
  expect(screen.getByRole('region', { name: '页面提示' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '关闭提示' })).toBeNull()
  act(() => vi.advanceTimersByTime(30000))
  expect(screen.getByRole('alert').textContent).toContain('列表加载失败')
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByRole('heading', { name: '我的工作' })).toBeTruthy()
})

it('keeps dialog actions in the native modal and preserves page priority', () => {
  function Page() {
    const [open, setOpen] = useState(true)
    return (
      <ErrorNoticeScope>
        <ErrorNoticeOutlet />
        <ActionNotice>页面操作失败</ActionNotice>
        {open && (
          <Modal title="删除报告" onClose={() => setOpen(false)}>
            <ActionNotice>删除失败</ActionNotice>
          </Modal>
        )}
      </ErrorNoticeScope>
    )
  }
  render(<Page />)
  const dialog = screen.getByRole('dialog', { name: '删除报告' })
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(within(dialog).getByRole('alert').textContent).toContain('删除失败')
  fireEvent.click(within(dialog).getByRole('button', { name: '关闭提示' }))
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.click(within(dialog).getByRole('button', { name: '关闭' }))
  expect(screen.getByRole('alert').textContent).toContain('页面操作失败')
})

it('keeps diagnostics and an actual retry with its cooldown while respecting permissions and cancellation', () => {
  const retry = vi.fn()
  const failure = new ApiError(429, 'limited', '请稍后重试', 'rate_limited', null, 30)
  const view = render(
    <MemoryRouter>
      <ErrorDiagnostics.Provider value={true}>
        <SupportLink.Provider value="/settings/support">
          <ActionNotice retry={retry}>{failure}</ActionNotice>
        </SupportLink.Provider>
      </ErrorDiagnostics.Provider>
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: '问题反馈' }).getAttribute('href')).toBe(
    '/settings/support',
  )
  act(() => vi.advanceTimersByTime(10000))
  expect(screen.getByRole('button', { name: '20 秒后重试' }).hasAttribute('disabled')).toBe(true)
  act(() => vi.advanceTimersByTime(20000))
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(retry).toHaveBeenCalledTimes(1)
  view.rerender(
    <ActionNotice retry={retry}>
      {new ApiError(403, 'forbidden', '无权操作', 'forbidden')}
    </ActionNotice>,
  )
  expect(screen.getByRole('alert').textContent).toContain('无权操作')
  expect(screen.queryByRole('button', { name: '重试' })).toBeNull()
  view.rerender(<ActionNotice>{new ApiError(0, 'cancelled', '', 'cancelled')}</ActionNotice>)
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByRole('button', { name: '关闭提示' })).toBeNull()
})
