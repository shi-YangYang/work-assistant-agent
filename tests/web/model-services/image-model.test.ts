import { expect, it } from 'vitest'
import {
  newModel,
  modelFieldErrors,
} from '../../../apps/web/src/features/model-services/utils/service-drafts'
import {
  matchModelProtocol,
  changeModelProtocol,
} from '../../../apps/web/src/features/model-services/utils/service-presets'
import {
  protocolPurpose,
  supportsPurpose,
} from '../../../apps/web/src/features/model-services/types'

it('recognizes native and Token Plan Wan and Pro without guessing unknown protocols', () => {
  expect(matchModelProtocol('https://dashscope.aliyuncs.com/api/v1', 'wan2.7-image').protocol).toBe(
    'dashscope-image',
  )
  expect(
    matchModelProtocol(
      'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
      'wan2.7-image',
    ).protocol,
  ).toBe('dashscope-image')
  expect(
    matchModelProtocol('https://dashscope.aliyuncs.com/api/v1', 'wan2.7-image-pro').protocol,
  ).toBe('dashscope-image')
  expect(protocolPurpose('dashscope-image')).toBe('image')
  for (const purpose of ['assistant', 'report', 'asr'] as const)
    expect(supportsPurpose('dashscope-image', purpose)).toBe(false)
  expect(supportsPurpose('chat', 'image')).toBe(false)
  expect(supportsPurpose('dashscope-asr', 'asr')).toBe(true)
})

it('clears incompatible options when switching to images and validates direct image drafts', () => {
  const old = {
    ...newModel('wan2.7-image'),
    language: 'zh',
    contextWindow: 1000,
    parameters: { enable_thinking: false },
  }
  const image = changeModelProtocol(old, 'dashscope-image')
  expect(image).toMatchObject({
    language: '',
    contextWindow: null,
    parameters: {},
    streaming: false,
    reasoning: { efforts: [], initial: null },
  })
  expect(Object.values(modelFieldErrors(image)).every((value) => !value)).toBe(true)
  expect(modelFieldErrors({ ...image, model: 'wan2.7-image-pro' }).imageSettings).toBe('')
  expect(modelFieldErrors({ ...image, model: 'future-image' }).imageSettings).toContain('请选')
})

it('allows a manually configured model and preserves its sizes in drafts', async () => {
  const { cleanServiceDraft, writableModels, validateServiceModels } =
    await import('../../../apps/web/src/features/model-services/utils/service-drafts')
  const model = {
    ...changeModelProtocol(newModel('future-image'), 'dashscope-image'),
    protocolMode: 'manual' as const,
    imageSettings: {
      api: 'multimodal-sync' as const,
      sizeMode: 'fixed' as const,
      sizes: ['1024*1024', '1536*1024'],
      defaultSize: '1024*1024',
    },
  }
  expect(() => validateServiceModels([model])).not.toThrow()
  const draft = cleanServiceDraft({
    id: 'test',
    name: '兼容服务',
    baseUrl: 'https://example.com/api/v1',
    models: [model],
    revision: 1,
    hasKey: true,
  })
  expect(writableModels(draft.models)[0].imageSettings).toEqual(model.imageSettings)
  expect(changeModelProtocol(model, 'chat').imageSettings).toBeUndefined()
  expect(modelFieldErrors({ ...model, model: 'another-image' }).imageSettings).toBe('')
})

it('rejects unsafe, duplicate or inconsistent size settings', () => {
  const model = changeModelProtocol(newModel('wan2.7-image'), 'dashscope-image')
  for (const sizes of [
    ['0*1024'],
    ['99999*99999'],
    ['1024*1024', '1024*1024'],
    Array.from({ length: 17 }, (_, i) => `${1024 + i}*1024`),
  ]) {
    expect(
      modelFieldErrors({
        ...model,
        imageSettings: { api: 'auto', sizeMode: 'fixed', sizes, defaultSize: sizes[0] },
      }).imageSettings,
    ).not.toBe('')
  }
  expect(
    modelFieldErrors({
      ...model,
      imageSettings: {
        api: 'auto',
        sizeMode: 'fixed',
        sizes: ['1024*1024'],
        defaultSize: '2048*2048',
      },
    }).imageSettings,
  ).not.toBe('')
  expect(
    modelFieldErrors({
      ...model,
      imageSettings: {
        api: 'auto',
        sizeMode: 'provider',
        sizes: ['1024*1024'],
        defaultSize: '1024*1024',
      },
    }).imageSettings,
  ).not.toBe('')
})
