// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { routePage } from '../../../apps/web/src/app/route-page'
import { deferred } from './helpers'

const page = { default: () => <p>页面内容</p> }
beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

async function advance(milliseconds: number) {
  await act(() => vi.advanceTimersByTimeAsync(milliseconds))
}

it('shows loading immediately and keeps it visible for at least 300ms even for a fast page', async () => {
  const request = deferred<typeof page>()
  const Page = routePage(() => request.promise)
  render(<Page />)
  expect(screen.getByRole('status').textContent).toBe('正在加载页面')
  await advance(100)
  await act(async () => request.resolve(page))
  await advance(199)
  expect(screen.getByRole('status')).toBeTruthy()
  expect(screen.queryByText('页面内容')).toBeNull()
  await advance(1)
  expect(screen.getByText('页面内容')).toBeTruthy()
  expect(screen.queryByRole('status')).toBeNull()
  expect(vi.getTimerCount()).toBe(0)
})

it('also shows loading for 300ms when returning to a cached page', async () => {
  const load = vi.fn().mockResolvedValue(page)
  const Page = routePage(load)
  const view = render(<Page />)
  await advance(300)
  expect(screen.getByText('页面内容')).toBeTruthy()
  view.unmount()
  render(<Page />)
  expect(screen.getByRole('status')).toBeTruthy()
  await advance(299)
  expect(screen.queryByText('页面内容')).toBeNull()
  await advance(1)
  expect(screen.getByText('页面内容')).toBeTruthy()
  expect(screen.queryByRole('status')).toBeNull()
  expect(load).toHaveBeenCalledTimes(1)
})

it('shows a slow page as soon as it is ready without another 300ms wait', async () => {
  const request = deferred<typeof page>()
  const load = vi.fn(() => request.promise)
  const Page = routePage(load)
  render(<Page />)
  await advance(1200)
  expect(screen.getByRole('status')).toBeTruthy()
  await act(async () => request.resolve(page))
  expect(screen.getByText('页面内容')).toBeTruthy()
  expect(screen.queryByRole('status')).toBeNull()
  expect(load).toHaveBeenCalledTimes(1)
  expect(vi.getTimerCount()).toBe(0)
})

it('keeps failure recovery available and retries a rejected module import', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  const request = deferred<typeof page>()
  const load = vi.fn().mockReturnValueOnce(request.promise).mockResolvedValue(page)
  const Page = routePage(load)
  render(<Page />)
  await act(async () => request.reject(new Error('network unavailable')))
  await advance(300)
  expect(screen.getByRole('alert').textContent).toContain('页面未能加载')
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '重新加载页面' })))
  expect(screen.getByRole('status')).toBeTruthy()
  await advance(300)
  expect(screen.getByText('页面内容')).toBeTruthy()
  expect(load).toHaveBeenCalledTimes(2)
})

it('cancels timers on navigation and does not publish an old page after switching away', async () => {
  const request = deferred<typeof page>()
  const load = vi.fn(() => request.promise)
  const Page = routePage(load)
  const view = render(
    <StrictMode>
      <Page />
    </StrictMode>,
  )
  await advance(150)
  await act(async () => request.resolve(page))
  view.rerender(<p>另一个页面</p>)
  expect(vi.getTimerCount()).toBe(0)
  await advance(1000)
  expect(screen.getByText('另一个页面')).toBeTruthy()
  expect(screen.queryByText('页面内容')).toBeNull()
  expect(load).toHaveBeenCalledTimes(1)
})
