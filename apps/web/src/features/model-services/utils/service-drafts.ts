import type { CompanyModel, CompanyService } from '@paa/api-contracts'
import { validateParameters } from '@paa/model-config'
import type { ServicePreset } from '@web/features/model-services/utils/service-presets'
import { resolveModelProtocol } from '@web/features/model-services/utils/service-presets'

export type ServiceDraft = Pick<
  CompanyService,
  'id' | 'name' | 'baseUrl' | 'models' | 'revision' | 'hasKey'
> & { providerPreset?: ServicePreset }

export function cleanServiceDraft(value: ServiceDraft): ServiceDraft {
  // Enumerate fields: unsaved credentials cannot enter the cross-page DraftStore.
  return {
    id: value.id,
    name: value.name,
    baseUrl: value.baseUrl,
    models: structuredClone(value.models),
    revision: value.revision,
    hasKey: value.hasKey,
    ...(value.providerPreset ? { providerPreset: value.providerPreset } : {}),
  }
}

export function newModel(model = '', baseUrl = ''): CompanyModel {
  return resolveModelProtocol(baseUrl, {
    id: crypto.randomUUID(),
    model,
    protocol: 'chat',
    protocolMode: 'auto',
    presets: [],
    selectedPresetId: null,
    streaming: true,
    language: '',
  })
}

export function appendServiceModels(draft: ServiceDraft, ids: string[]): ServiceDraft {
  const existing = new Set(draft.models.map((model) => model.model))
  const additions = [...new Set(ids.map((id) => id.trim()).filter(Boolean))].filter(
    (id) => !existing.has(id),
  )
  if (additions.some((id) => id.length > 200)) throw new Error('模型 ID 不能超过 200 个字符。')
  if (draft.models.length + additions.length > 32)
    throw new Error('每家服务最多添加 32 个模型，请减少选择。')
  return {
    ...draft,
    models: [...draft.models, ...additions.map((id) => newModel(id, draft.baseUrl))],
  }
}

export function serviceHasChanges(draft: ServiceDraft, saved?: CompanyService): boolean {
  return (
    !saved ||
    draft.name !== saved.name ||
    draft.baseUrl !== saved.baseUrl ||
    JSON.stringify(draft.models) !== JSON.stringify(saved.models)
  )
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
