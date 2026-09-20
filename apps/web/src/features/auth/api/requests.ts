import type { Identity, LoginProviders } from '@paa/api-contracts'
import { api, write } from '@web/api/client'

export function saveDingTalkConfiguration(body: {
  corpId: string
  clientId: string
  secret: string
  enabled: boolean
  expectedRevision: number
}) {
  return write('/settings/login/dingtalk', body, 'PUT')
}

export function dingTalkConfigurationPath() {
  return '/settings/login/dingtalk'
}

export function logout(body: Record<string, never>) {
  return write('/auth/logout', body)
}

export function desktopAuthorizationPath(valid: boolean, id: string) {
  return valid ? '/auth/desktop/requests/' + id : null
}

export function resolveDesktopAuthorization(id: string, body: { approve: boolean }) {
  return write('/auth/desktop/requests/' + id, body)
}

export function readLoginProviders(options: RequestInit) {
  return api<LoginProviders>('/auth/providers', options)
}

export function login(body: {
  username: FormDataEntryValue | null
  password: FormDataEntryValue | null
}) {
  return write<Identity>('/auth/login', body)
}

export function readIdentity(options: RequestInit) {
  return api<Identity>('/auth/me', options)
}

const dingTalkPaths = {
  login: '/auth/dingtalk/start',
  probe: '/settings/login/dingtalk/probe',
  reauthenticate: '/auth/dingtalk/account/reauth',
  bind: '/auth/dingtalk/account/bind',
} as const
export type DingTalkAction = keyof typeof dingTalkPaths
export function startDingTalkRedirect(action: DingTalkAction, body: unknown) {
  return write<{ url: string }>(dingTalkPaths[action], body)
}
