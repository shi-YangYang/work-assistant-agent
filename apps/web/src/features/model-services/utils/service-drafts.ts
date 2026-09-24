import type { CompanyModel, CompanyPreset, CompanyService } from '@paa/api-contracts'
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

export function modelFieldErrors(model: CompanyModel) {
  return {
    model:
      !model.model.trim() ||
      model.model.length > 200 ||
      [...model.model].some((character) => character.charCodeAt(0) < 32)
        ? '模型 ID 需为 1–200 个字符，不能全为空白或包含控制字符。'
        : '',
    language: !/^[a-zA-Z-]{0,20}$/.test(model.language)
      ? '识别语言只支持最多 20 位英文字母和连字符，例如 zh 或 zh-CN。'
      : '',
  }
}

export function presetFieldErrors(preset: CompanyPreset) {
  return {
    name: !preset.name.trim() || preset.name.length > 80 ? '预设名称需为 1–80 个字符。' : '',
    value:
      preset.mode === 'simple' && (!preset.value.trim() || preset.value.length > 512)
        ? '请输入 1–512 个字符的推理强度，不能全为空白。'
        : '',
  }
}

export function validateServiceModels(models: CompanyModel[]) {
  const seen = new Set<string>()
  for (const model of models) {
    const errors = modelFieldErrors(model)
    const message = errors.model || errors.language
    if (message) throw new Error(`${model.model || '未命名模型'}：${message}`)
    const identity = JSON.stringify([model.model, model.protocol])
    if (seen.has(identity)) throw new Error(`模型 ${model.model} 的接口配置重复，请修改或移除。`)
    seen.add(identity)
    for (const preset of model.presets) {
      const errors = presetFieldErrors(preset)
      const message = errors.name || errors.value
      if (message)
        throw new Error(`${model.model} 的预设 ${preset.name || '（未命名）'}：${message}`)
      validateCompanyParameters(
        preset.mode === 'simple' ? { reasoning_effort: preset.value } : preset.parameters,
      )
    }
  }
}

export function modelApiKeyError(value: string) {
  return value &&
    (!value.trim() ||
      value.length > 4096 ||
      [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) > 126))
    ? 'API 密钥需为最多 4096 位可打印 ASCII 字符，不能全为空白。'
    : ''
}

export function sameServiceAddress(left: string, right?: string) {
  return right !== undefined && left.replace(/\/+$/, '') === right.replace(/\/+$/, '')
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
