import type { CompanyModel, CompanyPreset } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { FormField } from '@web/components/FormField'
import { Modal } from '@web/components/Modal'
import type { Purpose } from '@web/features/model-services/types'
import { protocolNames } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { modelFieldErrors } from '@web/features/model-services/utils/service-drafts'
import { changeModelProtocol } from '@web/features/model-services/utils/service-presets'
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
  setPreset,
  setPresetJson,
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
    protocol: ('chat' | 'transcriptions' | 'qwen-asr' | 'dashscope-asr') | null
    reason: string
  } | null
  setTestPurpose: React.Dispatch<React.SetStateAction<Purpose>>
  setPreset: React.Dispatch<React.SetStateAction<CompanyPreset | null>>
  setPresetJson: React.Dispatch<React.SetStateAction<string>>
  update: (next: ServiceDraft) => void
  setActiveModel: React.Dispatch<React.SetStateAction<string>>
  error: string | Error
}) {
  const fields = model ? modelFieldErrors(model) : { model: '', language: '' }
  return (
    <>
      {modelOpen && model && draft && (
        <Modal
          title={`设置 ${model.model || '模型'}`}
          className="model-settings-dialog"
          onClose={() => setModelOpen(false)}
        >
          <fieldset disabled={!!busy} className="model-options" aria-label="模型配置">
            <div className="field-grid">
              <FormField
                label="模型 ID"
                value={model.model}
                maxLength={200}
                required
                error={fields.model}
                onChange={(e) => updateModel({ ...model, model: e.target.value })}
              />
              <div className="model-protocol-status" role="status">
                {automaticMatch && !automaticMatch.protocol
                  ? model.model
                    ? automaticMatch.reason
                    : '填写模型 ID 后自动匹配接口。'
                  : `${automaticMatch ? '已自动匹配' : '当前接口'}：${protocolNames[model.protocol]}`}
              </div>
              <details
                className="model-advanced full-field"
                key={model.id}
                open={!!automaticMatch && !automaticMatch.protocol}
              >
                <summary>接口与高级设置</summary>
                <label>
                  接口协议
                  <select
                    value={model.protocolMode === 'auto' ? 'auto' : model.protocol}
                    onChange={(e) => {
                      if (e.target.value === 'auto') {
                        updateModel({ ...model, protocolMode: 'auto' })
                      } else {
                        const protocol = e.target.value as CompanyModel['protocol']
                        updateModel({
                          ...changeModelProtocol(model, protocol),
                          protocolMode: 'manual',
                        })
                        setTestPurpose(protocol === 'chat' ? 'assistant' : 'asr')
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
              </details>
              {automaticMatch && !automaticMatch.protocol ? null : model.protocol === 'chat' ? (
                <>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={model.streaming}
                      onChange={(e) => updateModel({ ...model, streaming: e.target.checked })}
                    />
                    使用流式接口
                  </label>
                  <label>
                    推理预设
                    <select
                      value={model.selectedPresetId || ''}
                      onChange={(e) =>
                        updateModel({ ...model, selectedPresetId: e.target.value || null })
                      }
                    >
                      <option value="">服务默认</option>
                      {model.presets.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="card-actions full-field">
                    <button
                      disabled={model.presets.length >= 16}
                      onClick={() => {
                        setPreset({
                          id: crypto.randomUUID(),
                          name: '',
                          mode: 'simple',
                          value: '',
                          parameters: {},
                        })
                        setPresetJson('{}')
                      }}
                    >
                      添加预设
                    </button>
                    {model.selectedPresetId && (
                      <>
                        <button
                          onClick={() => {
                            const p = model.presets.find((p) => p.id === model.selectedPresetId)!
                            setPreset(structuredClone(p))
                            setPresetJson(JSON.stringify(p.parameters, null, 2))
                          }}
                        >
                          编辑预设
                        </button>
                        <button
                          onClick={() =>
                            updateModel({
                              ...model,
                              presets: model.presets.filter((p) => p.id !== model.selectedPresetId),
                              selectedPresetId: null,
                            })
                          }
                        >
                          删除预设
                        </button>
                      </>
                    )}
                  </div>
                </>
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
                className="text-button danger full-field"
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
          <div className="form-actions">
            <span className="muted">完成后记得保存服务</span>
            <button
              className="primary"
              disabled={!!fields.model || !!fields.language}
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
