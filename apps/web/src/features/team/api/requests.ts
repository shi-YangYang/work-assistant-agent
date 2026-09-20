import type { Member } from '@paa/api-contracts'
import { api } from '@web/api/client'

export function teamWorkspacePath(view: 'reports' | 'work', query: URLSearchParams) {
  return `/team/workspace/${view}?${query}`
}

export function readMemberForBreadcrumb(id: string, options: RequestInit) {
  return api<{ member: Member }>(`/team/members/${id}/work`, options)
}
