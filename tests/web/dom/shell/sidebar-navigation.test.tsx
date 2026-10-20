// @vitest-environment jsdom
import type { Identity } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Shell } from '../../../../apps/web/src/app/layout/Shell'
import { usePageReady } from '../../../../apps/web/src/components/feedback/PageReadiness'
import { useWorkspace } from '../../../../apps/web/src/lib/workspace'
import { createVault, dialogs, identity } from '../helpers'

const lifecycle = vi.hoisted(() => ({
  pageMount: vi.fn(),
  pageUnmount: vi.fn(),
  activityMount: vi.fn(),
  activityUnmount: vi.fn(),
}))

// Keep Shell, routing, notifications and the drawer real; no model or microphone is needed.
function AssistantFixture() {
  usePageReady(true)
  const { drafts, setDraft } = useWorkspace()
  const [answer, setAnswer] = useState('正在回复')
  useEffect(() => {
    lifecycle.pageMount()
    const append = () => setAnswer((text) => text + '，新文字')
    window.addEventListener('fixture-stream-delta', append)
    return () => {
      lifecycle.pageUnmount()
      window.removeEventListener('fixture-stream-delta', append)
    }
  }, [])
  return (
    <>
      <textarea
        aria-label="聊天草稿"
        value={String(drafts.message || '')}
        onChange={(event) => setDraft('message', event.target.value)}
      />
      <button onClick={() => setDraft('recording', !drafts.recording)}>
        {drafts.recording ? '结束测试录音' : '开始测试录音'}
      </button>
      <output>{answer}</output>
    </>
  )
}
vi.mock('@web/pages/AssistantPage', () => ({ AssistantPage: AssistantFixture }))
vi.mock('@web/pages/WorkPage', () => ({ WorkPage: () => <h1>工作页面</h1> }))
vi.mock('@web/features/settings/components/account/AccountPage', () => ({
  DingTalkAccountPage: () => <input aria-label="账户编辑" defaultValue="尚未保存" />,
}))
vi.mock('@web/features/settings/components/memory/MemoryPage', () => ({
  MemoryPage: () => <h1>记忆页面</h1>,
}))
vi.mock('@web/features/auth/components/DingTalkResult', () => ({ DingTalkResult: () => null }))
vi.mock('@web/hooks/useAssistantActivity', () => ({
  useAssistantActivity: () => {
    useEffect(() => {
      lifecycle.activityMount()
      return () => lifecycle.activityUnmount()
    }, [])
    return undefined
  },
}))

const admin = { ...identity, member: { ...identity.member, role: 'admin' as const } }
let drawerMedia: MediaQueryList
let breakpointListeners: Set<() => void>

beforeEach(() => {
  dialogs()
  sessionStorage.clear()
  localStorage.clear()
  Object.values(lifecycle).forEach((spy) => spy.mockClear())
  breakpointListeners = new Set()
  drawerMedia = {
    matches: false,
    addEventListener: (_: string, listener: () => void) => breakpointListeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => breakpointListeners.delete(listener),
  } as unknown as MediaQueryList
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => drawerMedia),
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ items: [], nextCursor: null }))),
  )
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(function () {
    return [{ width: 40, height: 44 }] as unknown as DOMRectList
  })
  HTMLElement.prototype.scrollIntoView = vi.fn()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function mount(path = '/assistant/current', account = identity) {
  const vault = createVault(account)
  let changeIdentity!: (next: Identity) => void
  function App() {
    const [current, setCurrent] = useState(account)
    changeIdentity = setCurrent
    return <Shell identity={current} onLogout={vi.fn()} vault={vault} />
  }
  const router = createMemoryRouter([{ path: '*', element: <App /> }], { initialEntries: [path] })
  const view = render(<RouterProvider router={router} />)
  return { ...view, router, vault, changeIdentity: (next: Identity) => changeIdentity(next) }
}

const settings = () => screen.getByRole('navigation', { name: '系统设置' })
const main = () => screen.getByRole('navigation', { name: '工作空间' })
const openSettings = () => fireEvent.click(screen.getByRole('button', { name: '系统设置' }))
const goBack = () => fireEvent.click(screen.getByRole('button', { name: '返回主菜单' }))
const visibleLinks = (nav: HTMLElement) =>
  within(nav)
    .getAllByRole('link')
    .map((node) => node.textContent)

it.each([identity, admin])(
  'toggles the initially hidden pet and remembers the browser preference for $member.role',
  async (account) => {
    const view = mount('/assistant/current', account)
    const draft = await screen.findByRole('textbox', { name: '聊天草稿' })
    fireEvent.change(draft, { target: { value: '保留草稿' } })
    expect(screen.queryByRole('button', { name: 'Noria' })).toBeNull()
    openSettings()
    const location = view.router.state.location
    const fetchCount = vi.mocked(fetch).mock.calls.length
    fireEvent.click(within(settings()).getByRole('button', { name: '显示宠物' }))
    expect(screen.getByRole('button', { name: 'Noria' })).toBeTruthy()
    expect(within(settings()).getByRole('button', { name: '隐藏宠物' })).toBeTruthy()
    expect(localStorage.getItem('paa.company.pet-visible')).toBe('true')
    expect(view.router.state.location).toBe(location)
    expect(screen.getByRole('textbox', { name: '聊天草稿' })).toBe(draft)
    expect(view.vault.getSnapshot().message).toBe('保留草稿')
    expect(fetch).toHaveBeenCalledTimes(fetchCount)
    view.unmount()

    const reopened = mount('/assistant/current', account)
    await screen.findByRole('textbox', { name: '聊天草稿' })
    expect(screen.getByRole('button', { name: 'Noria' })).toBeTruthy()
    openSettings()
    fireEvent.click(within(settings()).getByRole('button', { name: '隐藏宠物' }))
    expect(screen.queryByRole('button', { name: 'Noria' })).toBeNull()
    expect(within(settings()).getByRole('button', { name: '显示宠物' })).toBeTruthy()
    expect(localStorage.getItem('paa.company.pet-visible')).toBe('false')
    reopened.unmount()
    mount('/assistant/current', account)
    await screen.findByRole('textbox', { name: '聊天草稿' })
    expect(screen.queryByRole('button', { name: 'Noria' })).toBeNull()
  },
)

it('keeps the mobile drawer usable with the pet hidden and syncs visibility across tabs', async () => {
  Object.assign(drawerMedia, { matches: true })
  mount()
  await screen.findByRole('textbox', { name: '聊天草稿' })
  fireEvent.click(screen.getByRole('button', { name: '展开导航' }))
  openSettings()
  const drawer = screen.getByRole('dialog', { name: '导航' })
  fireEvent.click(within(drawer).getByRole('button', { name: '显示宠物' }))
  expect(screen.getByRole('dialog', { name: '导航' })).toBe(drawer)
  fireEvent.click(within(drawer).getByRole('button', { name: '隐藏宠物' }))
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: '导航' })).toBeNull()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '展开导航' }))
  act(() => {
    localStorage.setItem('paa.company.pet-visible', 'true')
    window.dispatchEvent(new StorageEvent('storage', { key: 'paa.company.pet-visible' }))
  })
  expect(screen.getByRole('button', { name: 'Noria' })).toBeTruthy()
  act(() => {
    localStorage.clear()
    window.dispatchEvent(new StorageEvent('storage', { key: null }))
  })
  expect(screen.queryByRole('button', { name: 'Noria' })).toBeNull()
})

it('keeps the pet toggle usable when browser storage is unavailable', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('Storage blocked')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('Storage blocked')
  })
  mount()
  await screen.findByRole('textbox', { name: '聊天草稿' })
  openSettings()
  fireEvent.click(within(settings()).getByRole('button', { name: '显示宠物' }))
  expect(screen.getByRole('button', { name: 'Noria' })).toBeTruthy()
  fireEvent.click(within(settings()).getByRole('button', { name: '隐藏宠物' }))
  expect(screen.queryByRole('button', { name: 'Noria' })).toBeNull()
})

it.each([
  [identity, ['记忆', '账户', '汇报规则', '问题反馈']],
  [
    admin,
    ['记忆', '用户声纹', '账户', '汇报规则', '登录方式', '模型服务管理', '模型用量', '问题反馈'],
  ],
])(
  'replaces the menu with the allowed settings in order and transfers focus for $member.role',
  async (account, entries) => {
    mount('/assistant/current', account)
    await screen.findByRole('textbox', { name: '聊天草稿' })
    const workspaceEntries = visibleLinks(main())
    expect(workspaceEntries).toEqual(
      account.member.role === 'admin'
        ? ['聊天搭子', '我的工作', '团队看板', '成员管理', '公告管理']
        : ['聊天搭子', '我的工作', '我的报告'],
    )
    expect(screen.getByRole('link', { name: '通知' }).getAttribute('href')).toBe('/notifications')
    expect(screen.getByRole('button', { name: '云搭子 beta' }).hasAttribute('disabled')).toBe(true)
    openSettings()
    expect(visibleLinks(settings())).toEqual(entries)
    expect(screen.queryByRole('navigation', { name: '工作空间' })).toBeNull()
    expect(screen.queryByRole('button', { name: '云搭子 beta' })).toBeNull()
    expect(screen.getByRole('link', { name: '通知' }).getAttribute('href')).toBe('/notifications')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '返回主菜单' }))
    goBack()
    expect(visibleLinks(main())).toEqual(workspaceEntries)
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '系统设置' }))
  },
)

it('shares unread state between hidden-pet navigation and its header entry without extra subscriptions', async () => {
  Object.assign(drawerMedia, { matches: true })
  let unread = 3
  vi.mocked(fetch).mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).includes('/notification-summary')
            ? { totalUnread: unread, remindersUnread: unread, announcementsUnread: 0 }
            : { items: [], nextCursor: null },
        ),
      ),
  )
  const view = mount()
  await screen.findByRole('textbox', { name: '聊天草稿' })
  const trigger = await screen.findByRole('button', { name: '展开导航，3 条未读通知' })
  fireEvent.click(trigger)
  const link = screen.getByRole('link', { name: '通知，3 条未读' })
  expect(link.textContent).toBe('3')
  const summaryRequests = () =>
    vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/notification-summary'))
      .length
  expect(summaryRequests()).toBe(1)
  openSettings()
  fireEvent.click(within(settings()).getByRole('button', { name: '显示宠物' }))
  expect(screen.queryByRole('link', { name: /^通知/ })).toBeNull()
  expect(screen.getByRole('button', { name: 'Noria，3 条未读通知' })).toBeTruthy()
  expect(summaryRequests()).toBe(1)
  fireEvent.click(within(settings()).getByRole('button', { name: '隐藏宠物' }))
  expect(screen.getByRole('link', { name: '通知，3 条未读' })).toBeTruthy()
  unread = 0
  act(() => window.dispatchEvent(new Event('paa-notifications-changed')))
  await screen.findByRole('link', { name: '通知' })
  expect(screen.queryByRole('button', { name: /条未读通知/ })).toBeNull()
  fireEvent.click(screen.getByRole('link', { name: '通知' }))
  await waitFor(() => expect(view.router.state.location.pathname).toBe('/notifications'))
  expect(screen.queryByRole('dialog', { name: '导航' })).toBeNull()
})

it('keeps route history, page instance, drafts, streaming and recording unchanged on menu switches', async () => {
  const { router, vault } = mount()
  const draft = await screen.findByRole('textbox', { name: '聊天草稿' })
  fireEvent.change(draft, { target: { value: '未发送内容' } })
  fireEvent.click(screen.getByRole('button', { name: '开始测试录音' }))
  const location = router.state.location
  const fetchCount = vi.mocked(fetch).mock.calls.length
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  openSettings()
  act(() => window.dispatchEvent(new Event('fixture-stream-delta')))
  expect(screen.getByText('正在回复，新文字')).toBeTruthy()
  expect(screen.getByRole('textbox', { name: '聊天草稿' })).toBe(draft)
  expect(vault.getSnapshot()).toMatchObject({ message: '未发送内容', recording: true })
  expect(router.state.location).toBe(location)
  expect(lifecycle.pageMount).toHaveBeenCalledTimes(1)
  expect(lifecycle.pageUnmount).not.toHaveBeenCalled()
  expect(lifecycle.activityMount).toHaveBeenCalledTimes(1)
  expect(lifecycle.activityUnmount).not.toHaveBeenCalled()
  expect(fetch).toHaveBeenCalledTimes(fetchCount)
  expect(confirm).not.toHaveBeenCalled()
  fireEvent.click(within(settings()).getByRole('link', { name: '账户' }))
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(router.state.location).toBe(location)
  expect(settings()).toBeTruthy()
  goBack()
  expect(router.state.location).toBe(location)
  expect(screen.getByRole('textbox', { name: '聊天草稿' })).toBe(draft)
})

it('restores the route menu after actual navigation and history, without reviving an old manual override', async () => {
  const { router, vault } = mount('/settings/account')
  const input = await screen.findByRole('textbox', { name: '账户编辑' })
  expect(within(settings()).getByRole('link', { name: '账户' }).getAttribute('aria-current')).toBe(
    'page',
  )
  goBack()
  expect(screen.getByRole('button', { name: '系统设置' }).getAttribute('data-active')).toBe('true')
  expect(within(main()).queryByRole('link', { current: 'page' })).toBeNull()
  act(() => vault.writer()('background-update', 'new data'))
  expect(main()).toBeTruthy()
  expect(screen.getByRole('textbox', { name: '账户编辑' })).toBe(input)
  fireEvent.click(within(main()).getByRole('link', { name: '我的工作' }))
  await screen.findByRole('heading', { name: '工作页面' })
  await act(() => router.navigate(-1))
  expect(settings()).toBeTruthy()
  await act(() => router.navigate(1))
  expect(main()).toBeTruthy()
  await act(() => router.navigate('/settings/account?tab=password'))
  expect(settings()).toBeTruthy()
  goBack()
  await act(() => router.navigate('/settings/account?tab=profile'))
  expect(settings()).toBeTruthy()
})

it('syncs command navigation, brand navigation and inaccessible settings route fallback', async () => {
  const { router } = mount('/settings/models')
  await screen.findByRole('textbox', { name: '账户编辑' })
  expect(router.state.location.pathname).toBe('/settings/account')
  expect(visibleLinks(settings())).not.toContain('模型服务管理')
  goBack()
  fireEvent.click(screen.getByRole('button', { name: '查找页面与操作' }))
  const dialog = screen.getByRole('dialog', { name: '查找页面与操作' })
  fireEvent.click(within(dialog).getByRole('option', { name: /记忆 管理跨会话/ }))
  await screen.findByRole('heading', { name: '记忆页面' })
  expect(settings()).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: 'Noria 首页' }))
  await screen.findByRole('textbox', { name: '聊天草稿' })
  expect(main()).toBeTruthy()
  expect(router.state.location.pathname).toBe('/assistant')
})

it('does not carry a manual menu choice across member, company or role changes', async () => {
  const { changeIdentity } = mount('/assistant/current', admin)
  await screen.findByRole('textbox', { name: '聊天草稿' })
  for (const next of [
    { ...admin, member: { ...admin.member, id: 'other' } },
    { ...admin, company: { ...admin.company, id: 'other-company' } },
    identity,
  ]) {
    openSettings()
    act(() => changeIdentity(next))
    expect(main()).toBeTruthy()
  }
  openSettings()
  expect(visibleLinks(settings())).toEqual(['记忆', '账户', '汇报规则', '问题反馈'])
})

it('preserves drawer focus and menu when closing or resizing', async () => {
  Object.assign(drawerMedia, { matches: true })
  mount('/assistant/current', admin)
  await screen.findByRole('textbox', { name: '聊天草稿' })
  openSettings()
  let drawer = screen.getByRole('dialog', { name: '导航' })
  expect(document.activeElement).toBe(within(drawer).getByRole('button', { name: '返回主菜单' }))
  fireEvent.keyDown(document.activeElement!, { key: 'Tab' })
  expect(document.activeElement).toBe(within(drawer).getByRole('button', { name: '退出登录' }))
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: '导航' })).toBeNull()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '展开导航' }))
  fireEvent.click(screen.getByRole('button', { name: '展开导航' }))
  expect(settings()).toBeTruthy()
  drawer = screen.getByRole('dialog', { name: '导航' })
  goBack()
  expect(screen.getByRole('dialog', { name: '导航' })).toBe(drawer)
  expect(document.activeElement).toBe(within(drawer).getByRole('button', { name: '系统设置' }))
  openSettings()
  act(() => {
    Object.assign(drawerMedia, { matches: false })
    breakpointListeners.forEach((listener) => listener())
  })
  expect(screen.queryByRole('dialog', { name: '导航' })).toBeNull()
  expect(settings()).toBeTruthy()
})

it('keeps the mobile drawer on menu changes, supports backdrop and Escape, and closes only for an accepted link', async () => {
  Object.assign(drawerMedia, { matches: true })
  const { router, vault } = mount()
  await screen.findByRole('textbox', { name: '聊天草稿' })
  fireEvent.click(screen.getByRole('button', { name: '展开导航' }))
  openSettings()
  const drawer = screen.getByRole('dialog', { name: '导航' })
  goBack()
  expect(screen.getByRole('dialog', { name: '导航' })).toBe(drawer)
  expect(within(drawer).queryByRole('button', { name: '收起导航' })).toBeNull()
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: '导航' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '展开导航' }))
  expect(main()).toBeTruthy()
  openSettings()
  const backdrop = screen
    .getAllByRole('button', { name: '收起导航' })
    .find((button) => button.tabIndex === -1)!
  fireEvent.click(backdrop)
  fireEvent.click(screen.getByRole('button', { name: '展开导航' }))
  expect(settings()).toBeTruthy()
  act(() => vault.writer()('recording', true))
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  fireEvent.click(within(settings()).getByRole('link', { name: '账户' }))
  expect(screen.getByRole('dialog', { name: '导航' })).toBeTruthy()
  expect(router.state.location.pathname).toBe('/assistant/current')
  confirm.mockReturnValue(true)
  fireEvent.click(within(settings()).getByRole('link', { name: '账户' }))
  await screen.findByRole('textbox', { name: '账户编辑' })
  expect(screen.queryByRole('dialog', { name: '导航' })).toBeNull()
  expect(settings()).toBeTruthy()
})
