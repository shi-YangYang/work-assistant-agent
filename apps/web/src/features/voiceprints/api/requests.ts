import { api, write } from '@web/api/client'
import type { Enrollment } from '@web/features/voiceprints/api/types'

export function uploadVoiceprint(item: Enrollment, options: RequestInit) {
  return api(`/settings/voiceprints/${item.memberId}`, options)
}

export function voiceprintsPath() {
  return '/settings/voiceprints'
}

export function manageVoiceprint(
  item: Enrollment,
  action: 'retry' | 'delete',
  body: Record<string, never>,
  method: 'POST' | 'DELETE',
) {
  return write(
    `/settings/voiceprints/${item.memberId}${action === 'retry' ? '/retry' : ''}`,
    body,
    method,
  )
}
