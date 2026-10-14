import type { CompanyModel, ImageModelSettings } from '@paa/api-contracts'

export const imageDefaults: ImageModelSettings = {
  api: 'auto',
  sizeMode: 'auto',
  sizes: [],
  defaultSize: null,
}
export const knownImageModels = ['wan2.7-image', 'wan2.7-image-pro']

export function imageSizeError(value: string) {
  if (!/^[1-9]\d{0,4}\*[1-9]\d{0,4}$/.test(value)) return '尺寸请填写正整数宽*高，例如 1024*1024。'
  const [width, height] = value.split('*').map(Number)
  return Math.max(width, height) > 16384 || width * height > 4096 ** 2
    ? '图片尺寸不能超过 16,777,216 总像素或 16,384 单边像素。'
    : ''
}

export function imageSettingsError(model: CompanyModel) {
  if (model.protocol !== 'dashscope-image')
    return model.imageSettings != null ? '只有图片接口接受图片设置。' : ''
  const settings = model.imageSettings ?? imageDefaults
  if (!['auto', 'multimodal-sync', 'image-async'].includes(settings.api))
    return '请选择支持的图片接口。'
  if (settings.api === 'auto' && !knownImageModels.includes(model.model))
    return '此模型没有自动接口规则，请选择同步多模态或异步图片接口。'
  if (!['auto', 'provider', 'fixed'].includes(settings.sizeMode)) return '请选择支持的尺寸模式。'
  if (settings.sizes.length > 16 || new Set(settings.sizes).size !== settings.sizes.length)
    return '可选尺寸最多 16 个，且不能重复。'
  for (const size of settings.sizes) {
    const error = imageSizeError(size)
    if (error) return error
  }
  if (settings.sizeMode === 'fixed')
    return !settings.sizes.length || !settings.sizes.includes(settings.defaultSize ?? '')
      ? '固定尺寸需要至少一个尺寸，默认尺寸必须属于可选尺寸。'
      : ''
  return settings.sizes.length || settings.defaultSize !== null
    ? '只有固定尺寸模式接受可选尺寸和默认尺寸。'
    : ''
}
