import type { CompanyModel, ImageModelSettings } from '@paa/api-contracts'
import { useId, useState } from 'react'
import { X } from 'lucide-react'
import {
  imageDefaults,
  imageSettingsError,
  imageSizeError,
  knownImageModels,
} from '../../utils/image-settings'
import styles from './ReasoningSettings.module.css'

export function ImageSettings({
  model,
  updateModel,
  onValidityChange,
}: {
  model: CompanyModel
  updateModel: (model: CompanyModel) => void
  onValidityChange: (invalid: boolean) => void
}) {
  const id = useId()
  const [text, setText] = useState('')
  const [entryError, setEntryError] = useState('')
  const settings = model.imageSettings ?? imageDefaults
  const update = (patch: Partial<ImageModelSettings>) =>
    updateModel({ ...model, imageSettings: { ...settings, ...patch } })
  const error = entryError || imageSettingsError(model)
  const addSize = () => {
    const size = text.trim().replace(/[xX×]/g, '*')
    const message = !size
      ? ''
      : imageSizeError(size) ||
        (settings.sizes.includes(size)
          ? '这个尺寸已经添加。'
          : settings.sizes.length >= 16
            ? '最多添加 16 个尺寸。'
            : '')
    setEntryError(message)
    if (message) return onValidityChange(true)
    if (size)
      update({ sizes: [...settings.sizes, size], defaultSize: settings.defaultSize ?? size })
    setText('')
    onValidityChange(false)
  }
  return (
    <section className={styles.settings} aria-label="图片生成设置">
      <label>
        图片请求方式
        <select
          value={settings.api}
          onChange={(event) => update({ api: event.target.value as ImageModelSettings['api'] })}
        >
          <option value="auto">自动匹配</option>
          <option value="multimodal-sync">同步多模态接口</option>
          <option value="image-async">异步图片接口</option>
        </select>
        <small>
          选择服务商支持的 DashScope 兼容接口；未知模型需手动选择，不会在失败后自动换接口重试。
        </small>
      </label>
      <label>
        图片尺寸
        <select
          value={settings.sizeMode}
          onChange={(event) => {
            const sizeMode = event.target.value as ImageModelSettings['sizeMode']
            update({ sizeMode, sizes: [], defaultSize: null })
            setText('')
            setEntryError('')
            onValidityChange(false)
          }}
        >
          <option value="auto">自动匹配模型能力</option>
          <option value="provider">使用服务商默认</option>
          <option value="fixed">指定可选尺寸</option>
        </select>
        <small>
          {settings.sizeMode === 'auto' && knownImageModels.includes(model.model)
            ? `${model.model} 默认 2K，支持 ${model.model.endsWith('-pro') ? '1K、2K、4K' : '1K、2K'}；聊天中可指定比例或像素。`
            : settings.sizeMode === 'fixed'
              ? '添加服务商允许的尺寸，聊天中的比例和宽高会按这些选项校验。'
              : '不指定尺寸时交给服务商；聊天中仍可指定明确像素，比例需配置可选尺寸。'}
        </small>
      </label>
      {settings.sizeMode === 'fixed' && (
        <>
          <div className={styles.field}>
            <label htmlFor={id}>可选尺寸</label>
            <div className={styles.tagInput} data-invalid={!!entryError}>
              {settings.sizes.map((size) => (
                <span className={styles.tag} key={size}>
                  {size.replace('*', ' × ')}
                  <button
                    type="button"
                    className={styles.tagRemove}
                    aria-label={`删除尺寸 ${size}`}
                    onClick={() => {
                      const sizes = settings.sizes.filter((value) => value !== size)
                      update({
                        sizes,
                        defaultSize: sizes.includes(settings.defaultSize ?? '')
                          ? settings.defaultSize
                          : (sizes[0] ?? null),
                      })
                    }}
                  >
                    <X size={13} aria-hidden="true" />
                  </button>
                </span>
              ))}
              <input
                id={id}
                value={text}
                placeholder="如 1024*1024，按 Enter 添加"
                autoComplete="off"
                aria-invalid={!!entryError}
                onChange={(event) => {
                  setText(event.target.value)
                  setEntryError('')
                  onValidityChange(!!event.target.value.trim())
                }}
                onKeyDown={(event) => {
                  if (
                    event.key === 'Enter' &&
                    !event.nativeEvent.isComposing &&
                    event.keyCode !== 229
                  ) {
                    event.preventDefault()
                    addSize()
                  }
                }}
              />
            </div>
          </div>
          {settings.sizes.length > 0 && (
            <label>
              默认尺寸
              <select
                value={settings.defaultSize ?? ''}
                onChange={(event) => update({ defaultSize: event.target.value })}
              >
                {settings.sizes.map((size) => (
                  <option key={size} value={size}>
                    {size.replace('*', ' × ')}
                  </option>
                ))}
              </select>
            </label>
          )}
        </>
      )}
      {error && (
        <small role="alert" className={styles.error}>
          {error}
        </small>
      )}
    </section>
  )
}
