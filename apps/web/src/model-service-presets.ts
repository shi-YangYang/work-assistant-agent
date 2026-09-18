import type { CompanyModel } from '@paa/api-contracts'

type Protocol = CompanyModel['protocol']
export const servicePresets = {
  'aliyun-token-plan': {
    name: '阿里 Token Plan',
    baseUrl: 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
  },
  'aliyun-beijing': {
    name: '阿里百炼 · 北京',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  'aliyun-singapore': {
    name: '阿里百炼 · 新加坡',
    baseUrl: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
  },
  custom: { name: '自定义服务', baseUrl: '' },
} as const
export type ServicePreset = keyof typeof servicePresets

export function detectServicePreset(baseUrl: string): ServicePreset {
  try {
    const url = new URL(baseUrl)
    if (
      url.protocol !== 'https:' ||
      url.port ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      !['/compatible-mode/v1', '/api/v1'].includes(url.pathname.replace(/\/$/, ''))
    )
      return 'custom'
    if (url.hostname === 'token-plan.cn-beijing.maas.aliyuncs.com') return 'aliyun-token-plan'
    if (
      url.hostname === 'dashscope.aliyuncs.com' ||
      /^[a-z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com$/.test(url.hostname)
    )
      return 'aliyun-beijing'
    if (
      url.hostname === 'dashscope-intl.aliyuncs.com' ||
      /^[a-z0-9-]+\.ap-southeast-1\.maas\.aliyuncs\.com$/.test(url.hostname)
    )
      return 'aliyun-singapore'
  } catch {
    /* An unfinished address stays custom. */
  }
  return 'custom'
}

export function matchModelProtocol(
  baseUrl: string,
  model: string,
): { protocol: Protocol | null; reason: string } {
  const provider = detectServicePreset(baseUrl)
  if (provider === 'custom')
    return { protocol: null, reason: '此服务尚无自动匹配规则，请在高级设置中选择接口协议。' }
  if (provider === 'aliyun-token-plan' && /^qwen3-asr-flash(?:-|$)/.test(model))
    return {
      protocol: null,
      reason:
        'Token Plan 的语音识别请使用 qwen-audio-3.0-asr-flash；qwen3-asr-flash 适用于百炼按量服务。',
    }
  // Explicit synchronous families only: filetrans, realtime, TTS and image
  // generation use different APIs and must never fall through to chat.
  if (/^qwen-audio-3\.0-asr-flash(?:-\d{4}-\d{2}-\d{2})?$/.test(model))
    return { protocol: 'dashscope-asr', reason: '' }
  if (/^qwen3-asr-flash(?:-\d{4}-\d{2}-\d{2})?$/.test(model)) {
    return baseUrl.replace(/\/$/, '').endsWith('/compatible-mode/v1')
      ? { protocol: 'qwen-asr', reason: '' }
      : {
          protocol: null,
          reason: '此模型需要 OpenAI 兼容服务地址，请使用以 /compatible-mode/v1 结尾的地址。',
        }
  }
  if (
    /(?:filetrans|realtime|streaming|tts)/.test(model) ||
    /^(?:wan|happyhorse|qwen-image)/.test(model)
  ) {
    return {
      protocol: null,
      reason: '此模型需要尚未支持的接口；如通过兼容网关接入，可在高级设置中手动选择。',
    }
  }
  // Known chat families from the connected catalogs; matching an API is not
  // a promise that this account/region has access to that model.
  if (
    /^(?:deepseek-v4(?:\.1)?-(?:flash|pro)|qwen3\.(?:6|7|8)-(?:flash|plus|max)|qwen-(?:turbo|plus|max)|glm-5\.2)(?:-(?:latest|\d{4}(?:-\d{2}){0,2}))?$/.test(
      model,
    )
  ) {
    return baseUrl.replace(/\/$/, '').endsWith('/compatible-mode/v1')
      ? { protocol: 'chat', reason: '' }
      : { protocol: null, reason: '聊天模型需要以 /compatible-mode/v1 结尾的服务地址。' }
  }
  return { protocol: null, reason: '尚未确认此模型的接口，请在高级设置中手动选择。' }
}

export function changeModelProtocol(model: CompanyModel, protocol: Protocol): CompanyModel {
  if (model.protocol === protocol) return model
  return {
    ...model,
    protocol,
    presets: [],
    selectedPresetId: null,
    streaming: protocol === 'chat',
    language: protocol === 'dashscope-asr' ? '' : model.language,
  }
}

export function resolveModelProtocol(baseUrl: string, model: CompanyModel): CompanyModel {
  if (model.protocolMode !== 'auto') return model
  const match = matchModelProtocol(baseUrl, model.model)
  return match.protocol ? changeModelProtocol(model, match.protocol) : model
}

export function requireModelProtocols(baseUrl: string, models: CompanyModel[]): CompanyModel[] {
  return models.map((model) => {
    if (model.protocolMode === 'auto') {
      const match = matchModelProtocol(baseUrl, model.model)
      if (!match.protocol) throw new Error(`${model.model || '新模型'}：${match.reason}`)
    }
    return resolveModelProtocol(baseUrl, model)
  })
}
