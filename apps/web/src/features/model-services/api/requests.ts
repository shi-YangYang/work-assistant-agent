import type {
  CompanyModel,
  CompanyService,
  ModelCheck,
  ModelRouting,
  ModelSelection,
} from '@paa/api-contracts'
import { api, write } from '@web/api/client'
import type { Purpose } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'

export function readModelRouting() {
  return api<ModelRouting>('/settings/model-routing')
}

export function saveModelRouting(body: {
  assistant: ModelSelection | null
  report: ModelSelection | 'follow' | null
  asr: ModelSelection | null
  expectedRevision: number
}) {
  return write('/settings/model-routing', body, 'PUT')
}

export function readModelService(draft: ServiceDraft) {
  return api<CompanyService>(`/settings/model-services/${draft.id}`)
}

export function modelServicesPath() {
  return '/settings/model-services'
}

export function saveModelService(
  target: ServiceDraft,
  body: {
    name: string
    baseUrl: string
    models: CompanyModel[]
    expectedRevision: number
    apiKey: string
  },
  method: 'POST' | 'PATCH',
) {
  return write<CompanyService>(
    target.revision ? `/settings/model-services/${target.id}` : '/settings/model-services',
    body,
    method,
  )
}

export function checkServiceConfiguration(
  kind: 'models' | 'test',
  body: {
    serviceId: string | null
    modelId: string | null
    purpose: Purpose
    draftVersion: string
    name: string
    baseUrl: string
    models: CompanyModel[]
    expectedRevision: number
    apiKey: string
  },
) {
  return write<
    { models: string[]; source: string; truncated: boolean; draftVersion: string } | ModelCheck
  >(`/settings/model-services/${kind}`, body)
}

export function deleteModelService(draft: ServiceDraft, body: { expectedRevision: number }) {
  return write(`/settings/model-services/${draft.id}`, body, 'DELETE')
}

export function importEnvironmentServices(body: Record<string, never>) {
  return write('/settings/model-services/import-environment', body)
}

export function modelUsagePath(query: URLSearchParams) {
  return `/settings/model-usage?${query}`
}
