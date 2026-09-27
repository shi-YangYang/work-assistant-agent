// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider, useLocation, useNavigate } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../../apps/web/src/app/AppRoutes'
import { identity } from './helpers'

const failing = vi.hoisted(() => ({ value: true }))
vi.mock('@web/pages/WorkDetailPage', () => ({
  WorkDetailPage: () => {
    if (failing.value) throw new Error('simulated route failure')
    return '工作详情'
  },
}))
vi.mock('@web/pages/WorkPage', () => ({ WorkPage: () => '工作列表' }))
afterEach(cleanup)
it('recovers a failed route locally without losing its deep link or browser back history', async () => {
  const loggedOut = vi.fn(),
    error = vi.spyOn(console, 'error').mockImplementation(() => {})
  function Shell() {
    const location = useLocation(),
      navigate = useNavigate()
    return (
      <>
        <span>{location.pathname + location.search}</span>
        <button onClick={() => void navigate(-1)}>返回上一页</button>
        <AppRoutes identity={identity} onLogout={loggedOut} />
      </>
    )
  }
  const router = createMemoryRouter([{ path: '*', element: <Shell /> }], {
    initialEntries: ['/work', '/work/a?revision=2'],
    initialIndex: 1,
  })
  try {
    render(<RouterProvider router={router} />)
    fireEvent.click(await screen.findByRole('button', { name: '重新加载页面' }))
    expect(await screen.findByText('页面未能加载，请检查网络后重试。')).toBeTruthy()
    failing.value = false
    fireEvent.click(screen.getByRole('button', { name: '重新加载页面' }))
    expect(await screen.findByText('工作详情')).toBeTruthy()
    expect(screen.getByText('/work/a?revision=2')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '返回上一页' }))
    expect(await screen.findByText('工作列表')).toBeTruthy()
    expect(loggedOut).not.toHaveBeenCalled()
  } finally {
    error.mockRestore()
  }
})
