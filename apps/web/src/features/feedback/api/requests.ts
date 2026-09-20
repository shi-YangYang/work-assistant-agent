import type { SupportFeedback, SupportFeedbackCreate } from '@paa/api-contracts'
import { api, write } from '@web/api/client'

export function feedbackListPath(scope: 'mine' | 'all', filterState: string) {
  return `/support-feedback?scope=${scope}${filterState ? `&state=${filterState}` : ''}`
}

export function submitFeedback(body: SupportFeedbackCreate, key: string) {
  return write<SupportFeedback>('/support-feedback', body, 'POST', key)
}

export function handleFeedback(
  selected: SupportFeedback,
  body: { state: 'pending' | 'resolved'; handlingNote: string; expectedRevision: number },
) {
  return write<SupportFeedback>(`/support-feedback/${selected.id}`, body, 'PATCH')
}

export function readFeedback(selected: SupportFeedback) {
  return api<SupportFeedback>(`/support-feedback/${selected.id}`)
}
