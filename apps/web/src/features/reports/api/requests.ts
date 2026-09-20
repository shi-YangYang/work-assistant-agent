import type {
  Identity,
  Report,
  ReportContent,
  ReportNotification,
  ReportObligation,
} from '@paa/api-contracts'
import { api, write } from '@web/api/client'

export function reportSourcesPath(report: Report) {
  return `/reports/${report.id}/sources?revision=${report.revision}`
}

export function reportDetailPath(id: string | undefined, search: string) {
  return `/reports/${id}${search}`
}

export function updateReport(
  id: string | undefined,
  body: { content: ReportContent; expectedRevision: number },
) {
  return write(`/reports/${id}`, body, 'PATCH')
}

export function generateReportCandidate(
  id: string | undefined,
  body: { expectedRevision: number },
) {
  return write(`/reports/${id}/candidate`, body)
}

export function readReport(id: string | undefined) {
  return api<Report>(`/reports/${id}`)
}

export function submitReport(
  id: string | undefined,
  body: { expectedRevision: number },
  key: string,
) {
  return write(`/reports/${id}/submit`, body, 'POST', key)
}

export function reportObligationsPath(team: boolean, query: URLSearchParams) {
  return `${team ? '/team' : ''}/report-obligations?${query}`
}

export function prepareReport(item: ReportObligation, body: Record<string, never>, key: string) {
  return write<{ reportId: string }>(`/report-obligations/${item.id}/prepare`, body, 'POST', key)
}

export function reportListPath(todo: boolean, kind: 'weekly' | 'daily') {
  return todo ? null : `/reports?kind=${kind}`
}

export function reportRulesPath() {
  return '/settings/report-rules'
}

export function generateReport(body: { kind: string; date: string }, key: string) {
  return write('/reports/generate', body, 'POST', key)
}

export function notificationsPath(identity: Identity, cursor: string) {
  return identity.member.role === 'employee' ? `/notifications?cursor=${cursor}` : null
}

export function markNotificationRead(item: ReportNotification, body: Record<string, never>) {
  return write(`/notifications/${item.id}/read`, body)
}

export function readReportForBreadcrumb(id: string, options: RequestInit) {
  return api<Report>(`/reports/${id}`, options)
}
