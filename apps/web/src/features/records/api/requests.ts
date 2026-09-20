import { write } from '@web/api/client'

export function deletionImpactPath(kind: 'work-items' | 'reports', id: string) {
  return kind === 'reports' ? `/reports/${id}/deletion` : null
}

export function deleteRecord(
  kind: 'work-items' | 'reports',
  id: string,
  body: { expectedRevision: number },
) {
  return write(`/${kind}/${id}`, body, 'DELETE')
}
