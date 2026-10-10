// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { MemberListItem } from '@paa/api-contracts'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, write } from '../../../apps/web/src/api/client'
import { MembersPage } from '../../../apps/web/src/features/members/components/overview/MembersPage'
import { MemberNameForm } from '../../../apps/web/src/features/members/components/forms/MemberNameForm'
import { TeamWorkspace } from '../../../apps/web/src/features/team/components/TeamWorkspace'
import { createVault, deferred, dialogs, TestWorkspace } from './helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))
const member: MemberListItem = {
  id: 'one',
  name: '张一',
  username: 'alpha',
  role: 'employee',
  active: true,
  hasPassword: true,
  createdAt: '2026-09-01T12:00:00Z',
}
const second: MemberListItem = { ...member, id: 'two', name: '李二', username: 'beta' }
function Location() {
  const location = useLocation()
  return <output data-testid="path">{location.pathname + location.search}</output>
}
function mount(path = '/members') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TestWorkspace vault={createVault()}>
        <Location />
        <Routes>
          <Route path="/members" element={<MembersPage />} />
          <Route path="/team" element={<TeamWorkspace renderDetail={() => null} />} />
        </Routes>
      </TestWorkspace>
    </MemoryRouter>,
  )
}
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  vi.mocked(api).mockResolvedValue({ items: [member, second] })
  vi.mocked(write).mockResolvedValue({})
})
afterEach(cleanup)

const staff = Array.from({ length: 41 }, (_, index) => ({
  ...member,
  id: `staff-${index + 1}`,
  name: `成员${String(index + 1).padStart(2, '0')}`,
  username: `staff${index + 1}`,
}))

it('paginates without more requests and preserves the page through refresh and work navigation', async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === '/members'
      ? { items: staff }
      : { items: [], counts: {}, total: 0, members: [], nextCursor: null },
  )
  mount('/members?page=2')
  await screen.findByRole('heading', { name: '成员21' })
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(21)
  expect(screen.queryByRole('heading', { name: '成员01' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  expect(screen.getByRole('heading', { name: '成员41' })).toBeTruthy()
  expect((screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '上一页' }))
  expect(screen.getByTestId('path').textContent).toBe('/members?page=2')
  expect(api).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByLabelText('刷新成员'))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
  expect(screen.getByText('第 2 页')).toBeTruthy()
  fireEvent.click(screen.getAllByLabelText('更多操作')[0])
  fireEvent.click(screen.getByRole('menuitem', { name: '查看工作' }))
  fireEvent.click(screen.getByRole('link', { name: '返回成员管理' }))
  await screen.findByRole('heading', { name: '成员21' })
  expect(screen.getByTestId('path').textContent).toBe('/members?page=2')
})

it('searches all members before pagination and resets to page one when the query changes', async () => {
  vi.mocked(api).mockResolvedValue({ items: staff })
  mount('/members?page=2')
  await screen.findByRole('heading', { name: '成员21' })
  fireEvent.change(screen.getByLabelText('搜索成员'), { target: { value: '成员41' } })
  expect(screen.getByRole('heading', { name: '成员41' })).toBeTruthy()
  expect(screen.getByText('找到 1 人，共 41 人')).toBeTruthy()
  expect(screen.getByRole('navigation', { name: '列表分页' })).toBeTruthy()
  expect((screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByTestId('path').textContent).not.toContain('page=')
  fireEvent.click(screen.getByLabelText('清除搜索'))
  expect(screen.getByRole('heading', { name: '成员01' })).toBeTruthy()
  expect((screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api).toHaveBeenCalledTimes(1)
})

it('clamps an out-of-range page and returns to the previous page after deleting its final member', async () => {
  let current = staff
  vi.mocked(api).mockImplementation(async (path) =>
    path === '/members' ? { items: current } : { voiceprints: 0, recordings: 0 },
  )
  vi.mocked(write).mockImplementation(async () => {
    current = staff.slice(0, -1)
    return { ok: true, cleanupPending: 0 }
  })
  mount('/members?page=99')
  await screen.findByRole('heading', { name: '成员41' })
  await waitFor(() => expect(screen.getByTestId('path').textContent).toBe('/members?page=3'))
  fireEvent.click(screen.getByLabelText('更多操作'))
  fireEvent.click(screen.getByRole('menuitem', { name: '删除账号' }))
  const remove = within(screen.getByRole('dialog')).getByRole('button', { name: '删除账号' })
  await waitFor(() => expect((remove as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(remove)
  await screen.findByRole('heading', { name: '成员21' })
  await waitFor(() => expect(screen.getByTestId('path').textContent).toBe('/members?page=2'))
  expect(screen.queryByRole('heading', { name: '成员41' })).toBeNull()
  expect(write).toHaveBeenCalledExactlyOnceWith('/members/staff-41', undefined, 'DELETE')
})

it('searches the loaded list, retains URL query on refresh and ignores the retired status filter', async () => {
  mount('/members?q=%20ALPHA%20&status=disabled')
  expect(await screen.findByRole('heading', { name: '张一' })).toBeTruthy()
  expect(screen.queryByRole('heading', { name: '李二' })).toBeNull()
  expect(screen.getByText('找到 1 人，共 2 人')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('搜索成员'), { target: { value: '李' } })
  expect(screen.getByRole('heading', { name: '李二' })).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(1)
  expect(screen.getByTestId('path').textContent).toBe('/members?q=%E6%9D%8E')
  fireEvent.click(screen.getByLabelText('刷新成员'))
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
  expect((screen.getByLabelText('搜索成员') as HTMLInputElement).value).toBe('李')
  fireEvent.click(screen.getByLabelText('更多操作'))
  expect(screen.queryByText(/停用账号|启用账号|正常|已停用/)).toBeNull()
  expect(screen.getByRole('menuitem', { name: '编辑姓名' })).toBeTruthy()
})

it('keeps loading distinct from zero, exposes retry on failure and clears an empty search', async () => {
  const pending = deferred<unknown>()
  vi.mocked(api).mockReturnValueOnce(pending.promise)
  mount('/members?q=不存在')
  expect(screen.getByText('正在读取成员…')).toBeTruthy()
  expect(screen.queryByText('0 人')).toBeNull()
  expect(screen.queryByText('没有匹配的成员')).toBeNull()
  await act(async () => pending.reject(new Error('读取失败')))
  expect(screen.getAllByText('读取失败')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await screen.findByText('没有匹配的成员')).toBeTruthy()
  fireEvent.click(screen.getAllByRole('button', { name: '清除搜索' })[0])
  expect(screen.getByRole('heading', { name: '张一' })).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(2)
})

it('navigates to one member current work and returns to the same search', async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path === '/members'
      ? { items: [member, second] }
      : { items: [], counts: {}, total: 0, members: [], nextCursor: null },
  )
  mount('/members?q=alpha')
  await screen.findByRole('heading', { name: '张一' })
  fireEvent.click(screen.getByLabelText('更多操作'))
  fireEvent.click(screen.getByRole('menuitem', { name: '查看工作' }))
  expect(screen.getByTestId('path').textContent).toBe(
    '/team?view=work&scope=current&member=one&members=all',
  )
  fireEvent.click(screen.getByRole('link', { name: '返回成员管理' }))
  await screen.findByRole('heading', { name: '张一' })
  expect(screen.getByTestId('path').textContent).toBe('/members?q=alpha')
})

it('validates name, prevents duplicate submission and preserves input on failure', async () => {
  const saved = vi.fn(),
    close = vi.fn(),
    pending = deferred<unknown>()
  vi.mocked(write).mockReturnValueOnce(pending.promise)
  render(
    <TestWorkspace vault={createVault()}>
      <MemberNameForm member={member} onClose={close} onSaved={saved} />
    </TestWorkspace>,
  )
  const name = screen.getByRole('textbox', { name: '姓名' }),
    submit = screen.getByRole('button', { name: '保存' })
  expect((screen.getByLabelText('账号') as HTMLInputElement).readOnly).toBe(true)
  fireEvent.change(name, { target: { value: '   ' } })
  fireEvent.click(submit)
  expect(screen.getByText('请输入姓名')).toBeTruthy()
  expect(document.activeElement).toBe(name)
  fireEvent.change(name, { target: { value: 'x'.repeat(81) } })
  fireEvent.click(submit)
  expect(write).not.toHaveBeenCalled()
  fireEvent.change(name, { target: { value: '  新姓名  ' } })
  fireEvent.click(submit)
  fireEvent.click(submit)
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(write).toHaveBeenCalledExactlyOnceWith('/members/one', { name: '新姓名' }, 'PATCH')
  expect(close).not.toHaveBeenCalled()
  await act(async () => pending.reject(new Error('保存失败')))
  expect(screen.getByText('保存失败')).toBeTruthy()
  expect((name as HTMLInputElement).value).toBe('  新姓名  ')
  expect(saved).not.toHaveBeenCalled()
  fireEvent.click(submit)
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
})

it('refreshes once after rename and keeps the query when the renamed member no longer matches', async () => {
  vi.mocked(api)
    .mockResolvedValueOnce({ items: [member, second] })
    .mockResolvedValue({ items: [{ ...member, name: '新姓名' }, second] })
  mount('/members?q=张一')
  await screen.findByRole('heading', { name: '张一' })
  fireEvent.click(screen.getByLabelText('更多操作'))
  fireEvent.click(screen.getByRole('menuitem', { name: '编辑姓名' }))
  const dialog = within(screen.getByRole('dialog'))
  fireEvent.change(dialog.getByRole('textbox', { name: '姓名' }), {
    target: { value: '新姓名' },
  })
  fireEvent.click(dialog.getByRole('button', { name: '保存' }))
  expect(await screen.findByText('没有匹配的成员')).toBeTruthy()
  expect(api).toHaveBeenCalledTimes(2)
  expect((screen.getByLabelText('搜索成员') as HTMLInputElement).value).toBe('张一')
})

it('shows an add entry for a loaded empty list and retains existing rows during failed refresh', async () => {
  vi.mocked(api)
    .mockResolvedValueOnce({ items: [] })
    .mockResolvedValueOnce({ items: [member] })
    .mockRejectedValueOnce(new Error('刷新失败'))
  mount()
  expect(await screen.findByRole('button', { name: '添加第一位成员' })).toBeTruthy()
  expect(screen.getByText('共 0 人')).toBeTruthy()
  expect(screen.getByText('第 1 页')).toBeTruthy()
  expect((screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByLabelText('刷新成员'))
  await screen.findByRole('heading', { name: '张一' })
  fireEvent.click(screen.getByLabelText('刷新成员'))
  expect(await screen.findByText('刷新失败')).toBeTruthy()
  expect(screen.getByRole('heading', { name: '张一' })).toBeTruthy()
})
