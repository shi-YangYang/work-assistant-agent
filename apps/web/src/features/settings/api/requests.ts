import type { Rules, Schedule } from '@paa/api-contracts'
import { api, write } from '@web/api/client'

export function dingTalkAccountPath() {
  return '/auth/dingtalk/account'
}

export function changePassword(body: {
  currentPassword: FormDataEntryValue | null
  newPassword: FormDataEntryValue | null
  useDingTalk: boolean
}) {
  return write('/auth/password', body)
}

export function unbindDingTalk(body: { currentPassword: string; useDingTalk: boolean }) {
  return write('/auth/dingtalk/account/unbind', body)
}

export function reportRulesPath() {
  return '/settings/report-rules'
}

export function saveReportRules(body: {
  timezone: string
  daily: Schedule
  weekly: Schedule
  expectedRevision: number
}) {
  return write('/settings/report-rules', body, 'PUT')
}

export function readReportRules() {
  return api<Rules>('/settings/report-rules')
}
