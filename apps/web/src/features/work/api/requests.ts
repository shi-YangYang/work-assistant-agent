import type {
  Draft,
  Progress,
  Work,
  WorkMessage,
  WorkDocument,
  WorkPatch,
  WorkUpdateInput,
  WorkWriteResult,
  WorkMaterial,
  WorkMaterialSource,
  WorkUpdate,
} from '@paa/api-contracts'
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

export function createWork(
  body: {
    title: string
    body?: WorkDocument
    dueDate?: string | null
    materials?: WorkMaterialSource[]
  },
  key: string,
) {
  return write<Work>('/work-items', body, 'POST', key)
}

export function workListPath(query: string, status: string) {
  return `/work-items?${new URLSearchParams({ q: query, status })}`
}

export function patchWork(id: string, body: WorkPatch, key: string) {
  return write<WorkWriteResult>(`/work-items/${id}`, body, 'PATCH', key)
}
export function workRecordsPath(work: Work, kind: 'materials' | 'updates', start = 0) {
  return `/work-items/${work.id}/${kind}?start=${start}&limit=20${work.historical ? `&revision=${work.revision}` : ''}`
}
export function saveWorkUpdate(
  workId: string,
  body: WorkUpdateInput,
  key: string,
  updateId?: string,
) {
  return write<WorkWriteResult>(
    `/work-items/${workId}/updates${updateId ? `/${updateId}` : ''}`,
    body,
    updateId ? 'PATCH' : 'POST',
    key,
  )
}
export function deleteWorkUpdate(
  work: Work,
  updateId: string,
  updateRevision: number,
  key: string,
) {
  return write<WorkWriteResult>(
    `/work-items/${work.id}/updates/${updateId}`,
    { expectedRevision: work.revision, expectedUpdateRevision: updateRevision },
    'DELETE',
    key,
  )
}
export function removeWorkMaterial(work: Work, material: WorkMaterial, key: string) {
  return write<WorkWriteResult>(
    `/work-items/${work.id}/materials/${material.id}`,
    { expectedRevision: work.revision, expectedMaterialRevision: material.revision },
    'DELETE',
    key,
  )
}

export async function readUpdateVersion(work: Work, updateId?: string) {
  const latest = await readWork(work)
  const update = updateId
    ? await api<WorkUpdate>(`/work-items/${work.id}/updates/${updateId}`)
    : undefined
  return { work: latest, update }
}
