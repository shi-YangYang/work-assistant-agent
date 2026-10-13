import type { CompanyModel, CompanyService, ContextCapability } from '@paa/api-contracts'
import { validateParameters } from '@paa/model-config'
import { imageSettingsError } from './image-settings'
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
    models: value.models.map(normalizeModelDraft),
    revision: value.revision,
    hasKey: value.hasKey,
    ...(value.providerPreset ? { providerPreset: value.providerPreset } : {}),
  }
}

// Only persisted browser drafts can still contain the obsolete wire shape.
export function normalizeModelDraft(model: CompanyModel): CompanyModel {
  const old = model as unknown as Record<string, unknown>
  if (!Array.isArray(old.presets))
    return {
      ...model,
      reasoning: model.reasoning ?? { efforts: [], initial: null },
      parameters: model.parameters ?? {},
    }
  const presets = old.presets as {
    id: string
    mode: string
    value: string
    parameters: CompanyModel['parameters']
    assistantEffort?: string
  }[]
  const chosen = presets.find((entry) => entry.id === old.selectedPresetId)
  const options = (entry: typeof chosen) =>
    entry ? (entry.mode === 'simple' ? { reasoning_effort: entry.value } : entry.parameters) : {}
  const initial = chosen?.assistantEffort ?? null
  const exposed = initial ? presets.filter((entry) => entry.assistantEffort) : []
  const result = {
    ...model,
    explicitReasoning: !!chosen,
    parameters: options(chosen),
    reasoning: {
      efforts: exposed.map((entry) => entry.assistantEffort!),
      initial,
      parameterOverrides: Object.fromEntries(
        exposed.map((entry) => [entry.assistantEffort!, options(entry)]),
      ),
    },
  }
  delete (result as unknown as Record<string, unknown>).presets
  delete (result as unknown as Record<string, unknown>).selectedPresetId
  return result
}

export function newModel(model = '', baseUrl = ''): CompanyModel {
  return resolveModelProtocol(baseUrl, {
    id: crypto.randomUUID(),
    model,
    protocol: 'chat',
    protocolMode: 'auto',
    reasoning: { efforts: [], initial: null },
    parameters: {},
    streaming: true,
    language: '',
  })
}

export function appendServiceModels(
  draft: ServiceDraft,
  ids: string[],
  capabilities?: Record<string, ContextCapability>,
): ServiceDraft {
  const existing = new Set(draft.models.map((model) => model.model))
  const additions = [...new Set(ids.map((id) => id.trim()).filter(Boolean))].filter(
    (id) => !existing.has(id),
  )
  if (additions.some((id) => id.length > 200)) throw new Error('模型 ID 不能超过 200 个字符。')
  if (draft.models.length + additions.length > 32)
    throw new Error('每家服务最多添加 32 个模型，请减少选择。')
  return {
    ...draft,
    models: [
      ...draft.models,
      ...additions.map((id) => ({
        ...newModel(id, draft.baseUrl),
        ...(capabilities?.[id] ? { contextCapability: capabilities[id] } : {}),
      })),
    ],
  }
}

export function serviceHasChanges(draft: ServiceDraft, saved?: CompanyService): boolean {
  return (
    !saved ||
    draft.name !== saved.name ||
    draft.baseUrl !== saved.baseUrl ||
    JSON.stringify(writableModels(draft.models)) !== JSON.stringify(writableModels(saved.models))
  )
}

export function modelFieldErrors(model: CompanyModel) {
  let reasoning = ''
  try {
    validateReasoning(model)
  } catch (error) {
    reasoning = (error as Error).message
  }
  return {
    reasoning,
    imageSettings: imageSettingsError(model),
    contextWindow:
      model.contextWindow != null &&
      (!Number.isInteger(model.contextWindow) ||
        model.contextWindow < 1 ||
        model.contextWindow > 10_000_000)
        ? '上下文窗口需为 1–10,000,000 的整数；留空使用自动值。'
        : '',
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

export function validateReasoning(model: CompanyModel) {
  const { efforts, initial, parameterOverrides = {} } = model.reasoning
  if (
    efforts.length > 16 ||
    new Set(efforts).size !== efforts.length ||
    efforts.some((effort) => !/^[a-z][a-z0-9_-]{0,31}$/.test(effort))
  )
    throw new Error('可选强度最多 16 个，不能重复；请填写实际档位，例如 low、high。')
  if ((efforts.length && !efforts.includes(initial ?? '')) || (!efforts.length && initial !== null))
    throw new Error('初始强度必须属于可选强度。')
  if (Object.keys(parameterOverrides).some((key) => !efforts.includes(key)))
    throw new Error('参数覆盖只能使用已配置的强度。')
  validateCompanyParameters(model.parameters)
  if (
    !parameterOverrides ||
    typeof parameterOverrides !== 'object' ||
    Array.isArray(parameterOverrides)
  )
    throw new Error('参数覆盖必须是 JSON 对象。')
  if (model.protocol !== 'chat' && (efforts.length || Object.keys(model.parameters).length))
    throw new Error('非聊天接口不接受聊天推理参数。')
  if (model.protocol === 'dashscope-image' && (model.language || model.contextWindow != null))
    throw new Error('图片接口不接受识别语言和上下文设置。')
  for (const effort of efforts) {
    const options = parameterOverrides[effort] ?? { ...model.parameters, reasoning_effort: effort }
    validateCompanyParameters(options)
    const reasoning = options.reasoning
    const values = 'reasoning_effort' in options ? [options.reasoning_effort] : []
    if (
      reasoning &&
      typeof reasoning === 'object' &&
      !Array.isArray(reasoning) &&
      'effort' in reasoning
    )
      values.push(parameterOverrides[effort] ? reasoning.effort : effort)
    const thinking = options.thinking
    if (
      !values.length ||
      values.some((value) => value !== effort) ||
      options.enable_thinking === false ||
      (thinking &&
        typeof thinking === 'object' &&
        !Array.isArray(thinking) &&
        ['disabled', 'off'].includes(String(thinking.type)))
    )
      throw new Error('思考强度必须与实际推理参数一致，且不能关闭思考。')
  }
}

export function validateServiceModels(models: CompanyModel[]) {
  const seen = new Set<string>()
  for (const model of models) {
    const errors = modelFieldErrors(model)
    const message =
      errors.model ||
      errors.language ||
      errors.contextWindow ||
      errors.reasoning ||
      errors.imageSettings
    if (message) throw new Error(`${model.model || '未命名模型'}：${message}`)
    const identity = JSON.stringify([model.model, model.protocol])
    if (seen.has(identity)) throw new Error(`模型 ${model.model} 的接口配置重复，请修改或移除。`)
    seen.add(identity)
    validateReasoning(model)
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

export function writableModels(models: CompanyModel[]): CompanyModel[] {
  return models.map((model) => {
    const value = normalizeModelDraft(model)
    delete value.contextCapability
    return value
  })
}
