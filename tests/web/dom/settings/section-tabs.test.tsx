// @vitest-environment jsdom
import type { DingTalkConfiguration, Rules } from '@paa/api-contracts'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, write } from '../../../../apps/web/src/api/client'
import { LoginMethods } from '../../../../apps/web/src/features/auth/components/configuration/LoginMethods'
import { DingTalkAccountPage } from '../../../../apps/web/src/features/settings/components/account/AccountPage'
import { RulesPage } from '../../../../apps/web/src/features/settings/components/rules/RulesPage'
import { createVault, dialogs, identity, TestWorkspace } from '../helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))

const admin = { ...identity, member: { ...identity.member, role: 'admin' as const } }
const schedule = {
  enabled: true,
  days: [0],
  generateTime: '09:00',
  deadline: '18:00',
  reminders: true,
  beforeMinutes: 30,
}
const rules = { revision: 1, timezone: 'Asia/Shanghai', weekly: schedule } as Rules
const configuration: DingTalkConfiguration = {
  corpId: 'ding123',
  clientId: 'app123',
  hasSecret: true,
  enabled: false,
  revision: 1,
  callbackUrl: 'https://example.test/callback',
  verifiedAt: null,
}

function mount(page: ReactNode, account: typeof identity = admin) {
  const vault = createVault(account)
  const router = createMemoryRouter([
    {
      path: '/',
      element: (
        <TestWorkspace account={account} vault={vault}>
          {page}
        </TestWorkspace>
      ),
    },
  ])
  return { ...render(<RouterProvider router={router} />), vault }
}

beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  vi.mocked(write).mockResolvedValue({ ok: true })
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  })
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('keeps account password drafts when switching tabs, including keyboard navigation', async () => {
  vi.mocked(api).mockResolvedValue({
    bound: false,
    hasPassword: true,
    available: true,
    passwordVerified: false,
  })
  const view = mount(<DingTalkAccountPage member={admin.member} onLogout={vi.fn()} />)
  await screen.findByRole('tab', { name: '钉钉账号关联' })
  expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe('account-tab-info')
  expect(view.container.querySelector('details')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: '修改密码' }))
  fireEvent.change(within(screen.getByRole('tabpanel')).getByLabelText(/^新密码/), {
    target: { value: 'draft-password' },
  })
  fireEvent.keyDown(screen.getByRole('tab', { name: '修改密码' }), { key: 'ArrowRight' })
  expect(document.activeElement).toBe(screen.getByRole('tab', { name: '钉钉账号关联' }))
  expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe('account-tab-dingtalk')
  fireEvent.click(screen.getByRole('tab', { name: '修改密码' }))
  expect(
    (within(screen.getByRole('tabpanel')).getByLabelText(/^新密码/) as HTMLInputElement).value,
  ).toBe('draft-password')
  expect(api).toHaveBeenCalledTimes(1)
  expect(write).not.toHaveBeenCalled()
})

it('opens the password tab after verified DingTalk account recovery', async () => {
  vi.mocked(api).mockResolvedValue({
    bound: true,
    hasPassword: true,
    available: true,
    passwordVerified: true,
  })
  mount(<DingTalkAccountPage member={admin.member} onLogout={vi.fn()} />)
  await waitFor(() =>
    expect(screen.getByRole('tab', { name: '修改密码' }).getAttribute('aria-selected')).toBe(
      'true',
    ),
  )
  expect(within(screen.getByRole('tabpanel')).getByLabelText(/^新密码/)).toBeTruthy()
})

it('keeps the employee account page as collapsible sections', async () => {
  vi.mocked(api).mockResolvedValue({
    bound: false,
    hasPassword: true,
    available: true,
    passwordVerified: false,
  })
  const view = mount(<DingTalkAccountPage member={identity.member} onLogout={vi.fn()} />, identity)
  await screen.findByText('验证密码并绑定钉钉')
  expect(screen.queryByRole('tablist')).toBeNull()
  expect(view.container.querySelectorAll('details')).toHaveLength(3)
})

it('reveals invalid rules in a hidden tab and preserves edits across tabs before saving', async () => {
  vi.mocked(api).mockResolvedValue({ ...rules, weekly: { ...schedule, days: [] } })
  const view = mount(<RulesPage />)
  fireEvent.change(await screen.findByLabelText('公司时区'), { target: { value: 'Asia/Tokyo' } })
  fireEvent.click(screen.getByRole('button', { name: '保存汇报规则' }))
  expect(write).not.toHaveBeenCalled()
  expect(screen.getByRole('tab', { name: '周报' }).getAttribute('aria-selected')).toBe('true')
  const panel = screen.getByRole('tabpanel')
  expect(panel.contains(document.activeElement)).toBe(true)
  expect(within(panel).getByText('周报请选择一个汇报日。')).toBeTruthy()
  fireEvent.click(within(panel).getByLabelText('周五'))
  fireEvent.click(screen.getByRole('tab', { name: '时间设置' }))
  expect((screen.getByLabelText('公司时区') as HTMLSelectElement).value).toBe('Asia/Tokyo')
  fireEvent.click(screen.getByRole('button', { name: '保存汇报规则' }))
  await waitFor(() =>
    expect(write).toHaveBeenCalledExactlyOnceWith(
      '/settings/report-rules',
      {
        timezone: 'Asia/Tokyo',

        weekly: { ...schedule, days: [4] },
        expectedRevision: 1,
      },
      'PUT',
    ),
  )
  expect(view.container.querySelector('details')).toBeNull()
})

it('preserves login credentials across tabs and the active tab after configuration refresh', async () => {
  vi.mocked(api).mockResolvedValue(configuration)
  const view = mount(<LoginMethods />)
  fireEvent.change(await screen.findByLabelText(/^企业 CorpId/), { target: { value: 'ding456' } })
  fireEvent.click(screen.getByRole('tab', { name: '授权与入口' }))
  expect((screen.getByRole('button', { name: '启用钉钉登录' }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  fireEvent.click(screen.getByRole('tab', { name: '钉钉后台配置' }))
  expect((screen.getByLabelText('回调地址') as HTMLInputElement).value).toBe(
    configuration.callbackUrl,
  )
  fireEvent.click(screen.getByRole('tab', { name: '钉钉企业内部应用' }))
  expect((screen.getByLabelText(/^企业 CorpId/) as HTMLInputElement).value).toBe('ding456')
  vi.mocked(api).mockResolvedValue({ ...configuration, corpId: 'ding456', revision: 2 })
  fireEvent.click(screen.getByRole('button', { name: '保存配置' }))
  await screen.findByText('配置已保存。请使用“验证授权”检查真实登录。')
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
  fireEvent.click(screen.getByRole('tab', { name: '授权与入口' }))
  await waitFor(() =>
    expect(
      (screen.getByRole('button', { name: '启用钉钉登录' }) as HTMLButtonElement).disabled,
    ).toBe(false),
  )
  vi.mocked(api).mockResolvedValue({
    ...configuration,
    corpId: 'ding456',
    revision: 3,
    enabled: true,
  })
  fireEvent.click(screen.getByRole('button', { name: '启用钉钉登录' }))
  await screen.findByRole('button', { name: '关闭钉钉登录' })
  expect(screen.getByRole('tab', { name: '授权与入口' }).getAttribute('aria-selected')).toBe('true')
  expect(write).toHaveBeenLastCalledWith(
    '/settings/login/dingtalk',
    {
      corpId: 'ding456',
      clientId: configuration.clientId,
      secret: '',
      enabled: true,
      expectedRevision: 2,
    },
    'PUT',
  )
  expect(view.container.querySelector('details')).toBeNull()
})
