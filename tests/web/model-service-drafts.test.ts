import { describe, expect, it } from 'vitest'
import {
  cleanServiceDraft,
  newModel,
  validateCompanyParameters,
} from '../../apps/web/src/model-service-drafts'
import {
  changeModelProtocol,
  detectServicePreset,
  matchModelProtocol,
  requireModelProtocols,
  resolveModelProtocol,
  servicePresets,
} from '../../apps/web/src/model-service-presets'

describe('company model drafts', () => {
  it('retains ordinary edits without retaining write-only credentials', () => {
    const model = newModel('long-model-id')
    const input = {
      id: 'draft',
      name: '服务',
      baseUrl: 'https://example.com/v1',
      models: [model],
      revision: 0,
      hasKey: false,
      apiKey: 'never-persist-me',
    }
    const stored = cleanServiceDraft(input)
    expect(JSON.stringify(stored)).not.toContain('never-persist-me')
    expect(stored.models[0].streaming).toBe(true)
    input.models[0].model = 'changed'
    expect(stored.models[0].model).toBe('long-model-id')
  })
  it('protects nested credentials, transport and resource controls with server-equivalent boundaries', () => {
    for (const invalid of [
      { headers: {} },
      { thinking: { max_tokens: 200 } },
      { reasoning_effort: '${secret}' },
      { stream: false },
      { timeout: 600 },
    ]) {
      expect(() => validateCompanyParameters(invalid)).toThrow()
    }
    expect(validateCompanyParameters({ reasoning_effort: 'high' })).toEqual({
      reasoning_effort: 'high',
    })
    expect(validateCompanyParameters({})).toEqual({})
  })
})

describe('service presets and protocol selection', () => {
  const tokenPlan = servicePresets['aliyun-token-plan'].baseUrl
  it.each([
    [tokenPlan, 'aliyun-token-plan'],
    ['https://dashscope.aliyuncs.com/compatible-mode/v1/', 'aliyun-beijing'],
    ['https://my-workspace.cn-beijing.maas.aliyuncs.com/api/v1', 'aliyun-beijing'],
    [
      'https://my-workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1',
      'aliyun-singapore',
    ],
    ['https://token-plan.cn-beijing.maas.aliyuncs.com.evil.example/compatible-mode/v1', 'custom'],
    ['https://gateway.example/compatible-mode/v1', 'custom'],
    ['https://dashscope-us.aliyuncs.com/compatible-mode/v1', 'custom'],
    ['https://dashscope.aliyuncs.com/apps/anthropic', 'custom'],
    ['https://user:secret@dashscope.aliyuncs.com/compatible-mode/v1', 'custom'],
  ])('recognizes only the supported official origins: %s', (baseUrl, expected) => {
    expect(detectServicePreset(baseUrl)).toBe(expected)
  })
  it.each([
    ['qwen-audio-3.0-asr-flash', 'dashscope-asr'],
    ['qwen3-asr-flash-2026-02-10', 'qwen-asr'],
    ['deepseek-v4.1-flash', 'chat'],
    ['qwen3.8-max', 'chat'],
    ['qwen-audio-3.0-asr-flash-filetrans', null],
    ['qwen3-asr-flash-realtime', null],
    ['qwen-audio-3.0-tts-plus', null],
    ['wan2.7-image', null],
    ['unknown-model', null],
  ])('distinguishes model API families: %s', (id, protocol) => {
    expect(matchModelProtocol(tokenPlan, id).protocol).toBe(protocol)
    const model = newModel(id, tokenPlan)
    if (protocol) expect(requireModelProtocols(tokenPlan, [model])[0].protocol).toBe(protocol)
    else expect(() => requireModelProtocols(tokenPlan, [model])).toThrow()
  })
  it('does not infer the same model on an unknown gateway or unsupported region', () => {
    for (const baseUrl of [
      'https://gateway.example/v1',
      'https://dashscope-us.aliyuncs.com/compatible-mode/v1',
    ]) {
      expect(matchModelProtocol(baseUrl, 'qwen3-asr-flash').protocol).toBeNull()
    }
    expect(
      matchModelProtocol('https://dashscope.aliyuncs.com/api/v1', 'deepseek-v4.1-flash').protocol,
    ).toBeNull()
  })
  it('preserves manual and previously saved protocols, including after reload', () => {
    const automatic = newModel('qwen-audio-3.0-asr-flash', tokenPlan)
    const manual = {
      ...changeModelProtocol(automatic, 'transcriptions'),
      protocolMode: 'manual' as const,
    }
    expect(resolveModelProtocol(tokenPlan, manual)).toEqual(manual)
    const legacy = { ...manual, protocolMode: undefined }
    expect(resolveModelProtocol(tokenPlan, legacy)).toEqual(legacy)
    expect(requireModelProtocols('https://custom.example/v1', [manual])).toEqual([manual])
    const draft = cleanServiceDraft({
      id: 'saved',
      name: 'custom',
      baseUrl: tokenPlan,
      models: [manual],
      revision: 1,
      hasKey: true,
    })
    expect(resolveModelProtocol(tokenPlan, JSON.parse(JSON.stringify(draft)).models[0])).toEqual(
      manual,
    )
  })
  it('clears chat-only settings when auto matching changes the API family', () => {
    const chat = {
      ...newModel('deepseek-v4.1-flash', tokenPlan),
      presets: [
        { id: 'high', name: 'High', mode: 'simple' as const, value: 'high', parameters: {} },
      ],
      selectedPresetId: 'high',
      language: 'zh',
    }
    const audio = resolveModelProtocol(tokenPlan, { ...chat, model: 'qwen-audio-3.0-asr-flash' })
    expect(audio).toMatchObject({
      protocol: 'dashscope-asr',
      streaming: false,
      presets: [],
      selectedPresetId: null,
      language: '',
    })
    const custom = 'https://gateway.example/v1'
    expect(() => requireModelProtocols(custom, [audio])).toThrow()
    expect(resolveModelProtocol(tokenPlan, { ...chat, streaming: false }).streaming).toBe(false)
  })
})
