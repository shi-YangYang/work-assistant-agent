import { protocolPurpose } from '@web/features/model-services/types'
import layoutStyles from '../../../../styles/layout.module.css'
import controlsStyles from '../../../../styles/controls.module.css'
import utilitiesStyles from '../../../../styles/utilities.module.css'
import modelServicesStyles from '../../styles/model-services.module.css'
import type { CompanyModel } from '@paa/api-contracts'
import { capacitySourceLabel } from '@web/utils/model-capacity'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { FormField } from '@web/components/forms/FormField'
import { Modal } from '@web/components/overlays/Modal'
import type { Purpose } from '@web/features/model-services/types'
import { protocolNames } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { modelFieldErrors } from '@web/features/model-services/utils/service-drafts'
import { changeModelProtocol } from '@web/features/model-services/utils/service-presets'
import { useState } from 'react'
import { ReasoningSettings } from './ReasoningSettings'
import { ImageSettings } from './ImageSettings'
import type * as React from 'react'

export function ModelOptions({
  modelOpen,
  model,
  draft,
  setModelOpen,
  busy,
  updateModel,
  automaticMatch,
  setTestPurpose,
  update,
  setActiveModel,
  error,
}: {
  modelOpen: boolean
  model: CompanyModel | undefined
  draft: ServiceDraft | undefined
  setModelOpen: React.Dispatch<React.SetStateAction<boolean>>
  busy: string
  updateModel: (next: CompanyModel) => void | undefined
  automaticMatch: {
    protocol: CompanyModel['protocol'] | null
    reason: string
  } | null
  setTestPurpose: React.Dispatch<React.SetStateAction<Purpose>>
  update: (next: ServiceDraft) => void
  setActiveModel: React.Dispatch<React.SetStateAction<string>>
  error: string | Error
}) {
  const [invalidParameters, setInvalidParameters] = useState(false)
  const fields = model
    ? modelFieldErrors(model)
    : { model: '', language: '', contextWindow: '', reasoning: '', imageSettings: '' }
  return (
    <>
      {modelOpen && model && draft && (
        <Modal
          title={`设置 ${model.model || '模型'}`}
          className={modelServicesStyles['model-settings-dialog']}
          bodyClassName={modelServicesStyles['model-settings-body']}
          onClose={() => {
            setInvalidParameters(false)
            setModelOpen(false)
          }}
        >
          <fieldset disabled={!!busy} aria-label="模型配置">
            <div
              className={`${layoutStyles['field-grid']} ${modelServicesStyles['slot-field-grid']}`}
            >
              <FormField
                label="模型 ID"
                value={model.model}
                maxLength={200}
                required
                error={fields.model}
                onChange={(e) =>
                  updateModel({ ...model, model: e.target.value, contextCapability: undefined })
                }
              />
              <div className={modelServicesStyles['model-protocol-status']} role="status">
                {automaticMatch && !automaticMatch.protocol
                  ? model.model
                    ? automaticMatch.reason
                    : '填写模型 ID 后自动匹配接口。'
                  : `${automaticMatch ? '已自动匹配' : '当前接口'}：${protocolNames[model.protocol]}`}
              </div>
              <details
                className={`${modelServicesStyles['model-advanced']} ${layoutStyles['full-field']}`}
                key={model.id}
                open={!!automaticMatch && !automaticMatch.protocol}
              >
                <summary>接口与高级设置</summary>
                <label>
                  接口协议
                  <select
                    value={model.protocolMode === 'auto' ? 'auto' : model.protocol}
                    onChange={(e) => {
                      setInvalidParameters(false)
                      if (e.target.value === 'auto') {
                        updateModel({ ...model, protocolMode: 'auto' })
                      } else {
                        const protocol = e.target.value as CompanyModel['protocol']
                        updateModel({
                          ...changeModelProtocol(model, protocol),
                          protocolMode: 'manual',
                        })
                        setTestPurpose(protocolPurpose(protocol))
                      }
                    }}
                  >
                    <option value="auto">自动匹配</option>
                    {Object.entries(protocolNames).map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                {model.protocol === 'chat' && (
                  <FormField
                    label="上下文窗口（tokens）"
                    type="number"
                    min={1}
                    max={10000000}
                    step={1}
                    value={model.contextWindow ?? ''}
                    placeholder={
                      model.contextCapability?.contextWindow
                        ? `自动：${model.contextCapability.contextWindow.toLocaleString('zh-CN')}`
                        : '窗口大小未配置'
                    }
                    hint={
                      model.contextWindow != null
                        ? '使用管理员配置；清空后恢复自动。'
                        : model.contextCapability?.contextWindow
                          ? `自动 ${model.contextCapability.contextWindow.toLocaleString('zh-CN')} tokens · ${capacitySourceLabel(model.contextCapability.source)}`
                          : '留空使用服务的自动值；未知窗口时无法显示使用比例。'
                    }
                    error={fields.contextWindow}
                    onChange={(event) =>
                      updateModel({
                        ...model,
                        contextWindow:
                          event.target.value === '' ? null : Number(event.target.value),
                      })
                    }
                  />
                )}
              </details>
              {automaticMatch && !automaticMatch.protocol ? null : model.protocol === 'chat' ? (
                <>
                  <label
                    className={`${layoutStyles['check-label']} ${modelServicesStyles['slot-check-label']}`}
                  >
                    <input
                      type="checkbox"
                      checked={model.streaming}
                      onChange={(e) => updateModel({ ...model, streaming: e.target.checked })}
                    />
                    使用流式接口
                  </label>
                  <ReasoningSettings
                    key={model.id}
                    model={model}
                    updateModel={updateModel}
                    onValidityChange={setInvalidParameters}
                  />
                </>
              ) : model.protocol === 'dashscope-image' ? (
                <ImageSettings
                  key={model.id}
                  model={model}
                  updateModel={updateModel}
                  onValidityChange={setInvalidParameters}
                />
              ) : (
                <FormField
                  label="识别语言（可选）"
                  value={model.language}
                  disabled={model.protocol === 'dashscope-asr'}
                  placeholder={model.protocol === 'dashscope-asr' ? '自动识别' : '例如 zh'}
                  maxLength={20}
                  error={fields.language}
                  onChange={(e) => updateModel({ ...model, language: e.target.value })}
                />
              )}
              <button
                className={`${controlsStyles['text-button']} ${layoutStyles['slot-text-button']} ${modelServicesStyles['slot-text-button']} ${controlsStyles['danger']} ${layoutStyles['full-field']}`}
                onClick={() => {
                  update({ ...draft, models: draft.models.filter((m) => m.id !== model.id) })
                  setActiveModel('')
                  setModelOpen(false)
                }}
              >
                移除此模型配置
              </button>
            </div>
          </fieldset>
          <ErrorNotice>{error}</ErrorNotice>
          <div
            className={`${layoutStyles['form-actions']} ${modelServicesStyles['slot-form-actions']}`}
          >
            <span className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}>
              完成后记得保存服务
            </span>
            <button
              className={`${controlsStyles['primary']} ${modelServicesStyles['slot-primary']}`}
              disabled={
                !!fields.model ||
                !!fields.language ||
                !!fields.contextWindow ||
                !!fields.reasoning ||
                !!fields.imageSettings ||
                invalidParameters
              }
              onClick={() => setModelOpen(false)}
            >
              完成
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}
