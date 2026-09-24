import type { Schedule } from '@paa/api-contracts'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi } from 'vitest'
import { TimeField } from '../../apps/web/src/components/TimeField'
import { loginConfigurationErrors } from '../../apps/web/src/features/auth/utils/login-configuration'
import {
  reportRuleErrors,
  revealRuleErrors,
} from '../../apps/web/src/features/settings/utils/rule-validation'

const schedule: Schedule = {
  enabled: true,
  days: [0],
  generateTime: '09:00',
  deadline: '18:00',
  reminders: true,
  beforeMinutes: 30,
}
const rules = (daily: Partial<Schedule> = {}) => ({
  daily: { ...schedule, ...daily },
  weekly: schedule,
})

it('reveals collapsed report sections before focusing the first invalid field on every attempt', () => {
  const sections = [
    { open: false, parentElement: null },
    { open: false, parentElement: null },
  ]
  const fields = sections.map((section) => ({
    closest: () => section,
    scrollIntoView: vi.fn(),
    focus: vi.fn(() => {
      expect(sections.every((item) => item.open)).toBe(true)
    }),
  }))
  const form = {
    querySelectorAll: vi.fn((selector: string) => {
      expect(selector).toBe('[aria-invalid="true"]')
      return fields
    }),
  } as unknown as HTMLFormElement
  revealRuleErrors(form)
  expect(fields[0].scrollIntoView).toHaveBeenCalledWith({ block: 'center' })
  expect(fields[0].focus).toHaveBeenCalledWith({ preventScroll: true })
  expect(fields[1].focus).not.toHaveBeenCalled()
  sections.forEach((section) => {
    section.open = false
  })
  revealRuleErrors(form)
  expect(fields[0].focus).toHaveBeenCalledTimes(2)
})

it('locates invalid report days and linked times, including a partially cleared disabled schedule', () => {
  expect(reportRuleErrors(rules())).toEqual({})
  expect(reportRuleErrors(rules({ days: [] }))).toHaveProperty(['daily.days'])
  expect(reportRuleErrors(rules({ deadline: '08:59' }))).toHaveProperty(['daily.deadline'])
  expect(reportRuleErrors(rules({ enabled: false, generateTime: '' }))).toHaveProperty([
    'daily.generateTime',
  ])
  expect(reportRuleErrors(rules({ enabled: false, generateTime: '', deadline: '' }))).toEqual({})
  expect(
    reportRuleErrors({ daily: schedule, weekly: { ...schedule, days: [0, 1] } }),
  ).toHaveProperty(['weekly.days'])
  for (const beforeMinutes of [-1, 1441, 1.5])
    expect(reportRuleErrors(rules({ beforeMinutes }))).toHaveProperty(['daily.beforeMinutes'])
  for (const beforeMinutes of [0, 1440])
    expect(reportRuleErrors(rules({ beforeMinutes }))).toEqual({})
})

it('rejects blank or internally spaced login identifiers and distinguishes preserving an existing secret', () => {
  const config = { corpId: 'ding123', clientId: 'app123', secret: '' }
  expect(loginConfigurationErrors(config, true)).toEqual({ corpId: '', clientId: '', secret: '' })
  expect(loginConfigurationErrors(config, false).secret).not.toBe('')
  for (const corpId of ['   ', 'ding 123', 'ding\t123'])
    expect(loginConfigurationErrors({ ...config, corpId }, true).corpId).not.toBe('')
  expect(loginConfigurationErrors({ ...config, clientId: 'app 123' }, true).clientId).not.toBe('')
  expect(loginConfigurationErrors({ ...config, secret: '   ' }, true).secret).not.toBe('')
  expect(loginConfigurationErrors({ ...config, corpId: ' ding123 ' }, true).corpId).toBe('')
})

it('associates report time failures with their input', () => {
  const html = renderToStaticMarkup(
    createElement(TimeField, {
      value: '08:00',
      onChange: () => {},
      error: '截止时间不得早于生成时间',
    }),
  )
  expect(html).toContain('aria-invalid="true"')
  expect(html).toContain('aria-describedby=')
  expect(html).toContain('role="alert"')
  expect(html).toContain('截止时间不得早于生成时间')
})
