import type { Draft, Progress, Work, WorkMessage } from '@paa/api-contracts'
import { api, ApiError, write } from '@web/api/client'

export function progressFieldErrors(error: unknown): Partial<Record<keyof Progress, string>> {
  return error instanceof ApiError ? error.fieldErrors : {}
}

export function availableWorkPath() {
  return '/work-items'
}

export function updateProgressDraft(
  draft: Draft,
  body: {
    workId: string | null
    expectedRevision: number
    dueDate?: string | null
    title: string
    summary: string
    status: 'in_progress' | 'blocked' | 'done'
    blocker: string
    nextStep: string
  },
) {
  return write(`/progress-drafts/${draft.id}`, body, 'PATCH')
}

export function readProgressSource(draft: Draft) {
  return api<WorkMessage>(`/messages/${draft.messageId}`)
}

export function updateWorkProgress(
  work: Work,
  body: {
    title: string
    summary: string
    status: 'in_progress' | 'blocked' | 'done'
    blocker: string
    nextStep: string
    dueDate: string | null | undefined
    sourceIds: string[]
    expectedRevision: number
  },
) {
  return write(`/work-items/${work.id}/progress`, body)
}

export function readWork(work: Work) {
  return api<Work>(`/work-items/${work.id}`)
}

export function workDetailPath(id: string | undefined, search: string) {
  return `/work-items/${id}${search}`
}

export function createWork(body: Progress, key: string) {
  return write('/work-items', body, 'POST', key)
}

export function workListPath(query: string, status: string) {
  return `/work-items?${new URLSearchParams({ q: query, status })}`
}

export function readWorkForBreadcrumb(id: string, options: RequestInit) {
  return api<Work>(`/work-items/${id}`, options)
}
