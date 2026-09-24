import type { DingTalkAccount, Identity } from '@paa/api-contracts'
import type { ComponentProps, ReactElement, ReactNode } from 'react'
import { isValidElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../apps/web/src/api/client'
import { ErrorNotice } from '../../apps/web/src/components/ErrorNotice'
import { FormField } from '../../apps/web/src/components/FormField'
import { login, startDingTalkRedirect } from '../../apps/web/src/features/auth/api/requests'
import { Login } from '../../apps/web/src/features/auth/components/Login'
import { changePassword, unbindDingTalk } from '../../apps/web/src/features/settings/api/requests'
import { DingTalkAccountPage } from '../../apps/web/src/features/settings/components/AccountPage'
import { PasswordForm } from '../../apps/web/src/features/settings/components/PasswordForm'
import type { SessionDrafts } from '../../apps/web/src/lib/session-drafts'

const hooks = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  cleanups: [] as (() => void)[],
  account: null as DingTalkAccount | null,
}))
vi.mock('react', async (load) => ({
  ...(await load<typeof import('react')>()),
  useState: <T>(initial: T | (() => T)) => {
    const slot = hooks.cursor++
    if (!(slot in hooks.slots))
      hooks.slots[slot] = typeof initial === 'function' ? (initial as () => T)() : initial
    return [
      hooks.slots[slot],
      (next: T | ((previous: T) => T)) => {
        hooks.slots[slot] =
          typeof next === 'function' ? (next as (previous: T) => T)(hooks.slots[slot] as T) : next
      },
    ]
  },
  useRef: <T>(initial: T) => {
    const slot = hooks.cursor++
    if (!(slot in hooks.slots)) hooks.slots[slot] = { current: initial }
    return hooks.slots[slot]
  },
  useEffect: (setup: () => (() => void) | void) => {
    const slot = hooks.cursor++
    if (slot in hooks.slots) return
    hooks.slots[slot] = true
    const cleanup = setup()
    if (cleanup) hooks.cleanups.push(cleanup)
  },
  useContext: () => null,
}))
vi.mock('react-router', async (load) => ({
  ...(await load<typeof import('react-router')>()),
  useLocation: () => ({ search: '' }),
}))
vi.mock('../../apps/web/src/features/auth/api/requests', () => ({
  login: vi.fn(),
  startDingTalkRedirect: vi.fn(),
  logout: vi.fn(),
}))
vi.mock('../../apps/web/src/features/settings/api/requests', () => ({
  changePassword: vi.fn(),
  unbindDingTalk: vi.fn(),
  dingTalkAccountPath: () => '/auth/dingtalk/account',
}))
vi.mock('../../apps/web/src/hooks/useResource', () => ({
  useResource: () => ({ data: hooks.account, refresh: vi.fn() }),
}))

const saved = vi.fn()
const refresh = vi.fn()
const focus = vi.fn()
const redirect = { busy: false, launch: vi.fn() }
const account = { bound: true, available: true, passwordVerified: false } as DingTalkAccount
const passwordProps = { account, hasPassword: true, redirect, onSaved: saved, onFailure: refresh }
const loginProps = { vault: {} as SessionDrafts, onLogin: saved, initialError: '' }

function descendants(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(descendants)
  if (!isValidElement<Record<string, unknown>>(node)) return []
  return [node, ...descendants(node.props.children as ReactNode)]
}

function view(node: ReactNode) {
  const elements = descendants(node)
  const form = elements.find((element) => element.type === 'form')!.props as ComponentProps<'form'>
  ;(form.ref as { current: unknown }).current = {
    elements: { namedItem: (name: string) => ({ focus: () => focus(name) }) },
  }
  const field = (name: string) =>
    elements.find(
      (element) =>
        (element.type === FormField || element.type === 'input') && element.props.name === name,
    )?.props as ComponentProps<typeof FormField> | undefined
  return {
    form,
    field,
    elements,
    failure: elements.find((element) => element.type === ErrorNotice)!.props.children,
    change: (name: string, value: string) =>
      field(name)!.onChange!({ currentTarget: { value } } as never),
    blur: (name: string) => field(name)!.onBlur!({} as never),
    submit: () => form.onSubmit!({ preventDefault: vi.fn() } as never) as unknown as Promise<void>,
  }
}

function password(overrides: Partial<ComponentProps<typeof PasswordForm>> = {}) {
  hooks.cursor = 0
  return view(PasswordForm({ ...passwordProps, ...overrides }))
}

function loginForm() {
  hooks.cursor = 0
  return view(Login(loginProps))
}

function fillPassword(value = '1111') {
  password().change('currentPassword', '1')
  password().change('newPassword', value)
  password().change('confirmPassword', value)
}

function accountPage() {
  hooks.cursor = 0
  const elements = descendants(DingTalkAccountPage({ onLogout: saved }))
  const localPassword = elements.find((element) => element.type === FormField)!
    .props as unknown as ComponentProps<typeof FormField>
  return {
    field: localPassword,
    change: (value: string) => localPassword.onChange!({ currentTarget: { value } } as never),
    click: (label: string) => {
      const button = elements.find((element) => element.props.children === label)!
        .props as ComponentProps<'button'>
      return button.onClick!({} as never) as unknown as Promise<void>
    },
  }
}

beforeEach(() => {
  hooks.cleanups.forEach((cleanup) => cleanup())
  hooks.cleanups = []
  hooks.slots = []
  vi.clearAllMocks()
  vi.mocked(changePassword).mockReset().mockResolvedValue({})
  vi.mocked(login)
    .mockReset()
    .mockResolvedValue({} as Identity)
  vi.mocked(startDingTalkRedirect).mockReset()
  vi.mocked(unbindDingTalk).mockReset().mockResolvedValue({})
  hooks.account = { ...account, hasPassword: true }
})

afterEach(() => vi.unstubAllGlobals())

it('reports required and password range errors, then accepts a 4-character new password with an old short password', async () => {
  expect(password().form.noValidate).toBe(true)
  await password().submit()
  expect(password().field('currentPassword')!.error).toBe('请输入当前密码')
  expect(focus).toHaveBeenLastCalledWith('currentPassword')
  fillPassword('111')
  await password().submit()
  expect(password().field('newPassword')!.error).toContain('4–128')
  expect(focus).toHaveBeenLastCalledWith('newPassword')
  expect(changePassword).not.toHaveBeenCalled()
  fillPassword()
  await password().submit()
  expect(changePassword).toHaveBeenCalledExactlyOnceWith({
    currentPassword: '1',
    newPassword: '1111',
    useDingTalk: false,
  })
  expect(saved).toHaveBeenCalledOnce()
})

it('counts Unicode characters consistently and leaves an overlong password visible for correction', async () => {
  fillPassword('🔑'.repeat(129))
  await password().submit()
  expect(password().field('newPassword')!.error).toContain('4–128')
  expect(password().field('newPassword')!.value).toBe('🔑'.repeat(129))
  expect(changePassword).not.toHaveBeenCalled()
  fillPassword('🔑'.repeat(128))
  await password().submit()
  expect(changePassword).toHaveBeenCalledOnce()
})

it('places mismatch errors under confirmation and revalidates them when the new password changes', async () => {
  fillPassword()
  password().change('confirmPassword', '2222')
  password().blur('confirmPassword')
  expect(password().field('confirmPassword')!.error).toBe('两次新密码不一致')
  await password().submit()
  expect(changePassword).not.toHaveBeenCalled()
  expect(focus).toHaveBeenLastCalledWith('confirmPassword')
  password().change('newPassword', '2222')
  expect(password().field('confirmPassword')!.error).toBe('')
})

it('preserves server field errors until edited and understands legacy validation paths', async () => {
  fillPassword()
  const invalid = new ApiError(400, 'invalid_password', '当前密码不正确', 'validation')
  invalid.fieldErrors = { currentPassword: '当前密码不正确，请重新输入' }
  vi.mocked(changePassword).mockRejectedValueOnce(invalid)
  await password().submit()
  expect(password().field('currentPassword')!.error).toBe('当前密码不正确，请重新输入')
  expect(focus).toHaveBeenLastCalledWith('currentPassword')
  password().blur('currentPassword')
  expect(password().field('currentPassword')!.error).toBe('当前密码不正确，请重新输入')
  expect(password().failure).toBe('')
  password().change('currentPassword', 'correct')
  expect(password().field('currentPassword')!.error).toBe('')
  const legacy = new ApiError(422, 'validation_error', '输入不合法', 'validation')
  legacy.fields = ['body.newPassword']
  vi.mocked(changePassword).mockRejectedValueOnce(legacy)
  await password().submit()
  expect(password().field('newPassword')!.error).toContain('4–128')
  expect(refresh).toHaveBeenCalledTimes(2)
})

it('requires DingTalk verification before setting a password and keeps proof-expiry failures visible', async () => {
  const noPassword = { hasPassword: false }
  expect(password(noPassword).field('currentPassword')).toBeUndefined()
  expect(password(noPassword).field('newPassword')!.disabled).toBe(true)
  await password(noPassword).submit()
  expect(changePassword).not.toHaveBeenCalled()
  const verified = { hasPassword: false, account: { ...account, passwordVerified: true } }
  password(verified).change('newPassword', '1234')
  password(verified).change('confirmPassword', '1234')
  expect(password(verified).field('newPassword')!.disabled).toBe(false)
  const expired = new ApiError(
    400,
    'verification_expired',
    '钉钉验证已过期，请重新验证',
    'validation',
  )
  vi.mocked(changePassword).mockRejectedValueOnce(expired)
  await password(verified).submit()
  expect(changePassword).toHaveBeenCalledExactlyOnceWith({
    currentPassword: '',
    newPassword: '1234',
    useDingTalk: true,
  })
  expect(password(verified).failure).toBe(expired)
  expect(refresh).toHaveBeenCalledOnce()
  expect(saved).not.toHaveBeenCalled()
})

it('prevents duplicate password requests and reports network failures without clearing inputs', async () => {
  fillPassword()
  let reject!: (reason: Error) => void
  vi.mocked(changePassword).mockImplementationOnce(
    () => new Promise((_, rejectRequest) => (reject = rejectRequest)),
  )
  const pending = password().submit()
  await password().submit()
  expect(changePassword).toHaveBeenCalledOnce()
  expect(password().field('newPassword')!.readOnly).toBe(true)
  const offline = new ApiError(0, 'network', '无法连接服务', 'network')
  reject(offline)
  await pending
  expect(password().failure).toBe(offline)
  expect(password().field('newPassword')!.value).toBe('1111')
  expect(password().form['aria-busy']).toBe(false)
})

it('shows login field errors inline while accepting an existing one-character account and password', async () => {
  await loginForm().submit()
  expect(loginForm().form.noValidate).toBe(true)
  expect(loginForm().field('username')!['aria-invalid']).toBe(true)
  expect(loginForm().field('username')!['aria-describedby']).toBe('login-username-error')
  expect(focus).toHaveBeenLastCalledWith('username')
  expect(login).not.toHaveBeenCalled()
  loginForm().change('username', '1')
  loginForm().change('password', '1')
  await loginForm().submit()
  expect(login).toHaveBeenCalledExactlyOnceWith({ username: '1', password: '1' })
  expect(loginForm().field('password')!['aria-invalid']).toBeUndefined()
})

it('maps login API field errors and keeps unknown invalid credentials as a form-level message', async () => {
  loginForm().change('username', 'person')
  loginForm().change('password', '1111')
  const invalid = new ApiError(422, 'validation_error', '输入不合法', 'validation')
  invalid.fieldErrors = { username: '账号不能超过 80 位' }
  vi.mocked(login).mockRejectedValueOnce(invalid)
  await loginForm().submit()
  expect(loginForm().field('username')!['aria-invalid']).toBe(true)
  expect(loginForm().failure).toBe('')
  loginForm().change('username', 'other')
  expect(loginForm().field('username')!['aria-invalid']).toBeUndefined()
  const credentials = new ApiError(
    401,
    'invalid_credentials',
    '账号或密码不正确，请重新输入。',
    'unauthorized',
  )
  vi.mocked(login).mockRejectedValueOnce(credentials)
  await loginForm().submit()
  expect(loginForm().failure).toBe(credentials)
})

it('rejects overlong local passwords and places DingTalk binding failures below the password field', async () => {
  hooks.account = { ...account, hasPassword: true, bound: false }
  accountPage().change('x'.repeat(129))
  await accountPage().click('验证密码并绑定钉钉')
  expect(accountPage().field.error).toContain('128')
  expect(startDingTalkRedirect).not.toHaveBeenCalled()
  accountPage().change('1')
  const invalid = new ApiError(400, 'invalid_password', '密码不正确', 'validation')
  invalid.fieldErrors = { currentPassword: '当前密码不正确，请重新输入' }
  vi.mocked(startDingTalkRedirect).mockRejectedValueOnce(invalid)
  await accountPage().click('验证密码并绑定钉钉')
  await vi.waitFor(() => expect(accountPage().field.error).toBe('当前密码不正确，请重新输入'))
  expect(startDingTalkRedirect).toHaveBeenCalledExactlyOnceWith('bind', { currentPassword: '1' })
  accountPage().field.onBlur!({} as never)
  expect(accountPage().field.error).toBe('当前密码不正确，请重新输入')
  accountPage().change('correct')
  expect(accountPage().field.error).toBe('')
})

it('places DingTalk unbinding password failures inline without logging out', async () => {
  const invalid = new ApiError(400, 'invalid_password', '密码不正确', 'validation')
  invalid.fieldErrors = { currentPassword: '当前密码不正确，请重新输入' }
  vi.mocked(unbindDingTalk).mockRejectedValueOnce(invalid)
  vi.stubGlobal('window', { confirm: () => true })
  accountPage().change('1')
  await accountPage().click('解绑并重新登录')
  expect(unbindDingTalk).toHaveBeenCalledExactlyOnceWith({
    currentPassword: '1',
    useDingTalk: false,
  })
  expect(accountPage().field.error).toBe('当前密码不正确，请重新输入')
  expect(saved).not.toHaveBeenCalled()
})
