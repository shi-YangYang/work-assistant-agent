import type { CompanyModel, CompanyService } from '../shared/company-contracts'
import { validateParameters } from '../shared/reasoning'

export type ServiceDraft = Pick<
  CompanyService,
  'id' | 'name' | 'baseUrl' | 'models' | 'revision' | 'hasKey'
>
export function cleanServiceDraft(value: ServiceDraft): ServiceDraft {
  // Enumerate fields: unsaved credentials cannot enter the cross-page DraftStore.
  return {
    id: value.id,
    name: value.name,
    baseUrl: value.baseUrl,
    models: structuredClone(value.models),
    revision: value.revision,
    hasKey: value.hasKey,
  }
}
export function newModel(model = ''): CompanyModel {
  return {
    id: crypto.randomUUID(),
    model,
    protocol: 'chat',
    presets: [],
    selectedPresetId: null,
    streaming: true,
    language: '',
  }
}
export function validateCompanyParameters(value: unknown) {
  validateParameters(value)
  const protectedResources = new Set([
    'max_tokens',
    'max_completion_tokens',
    'max_output_tokens',
    'timeout',
    'max_retries',
    'stop',
    'logprobs',
    'top_logprobs',
  ])
  const walk = (item: unknown) => {
    if (!item || typeof item !== 'object') return
    for (const [key, child] of Object.entries(item)) {
      if (protectedResources.has(key.toLowerCase())) throw new Error('推理参数不能覆盖资源限制。')
      walk(child)
    }
  }
  walk(value)
  return value
}
