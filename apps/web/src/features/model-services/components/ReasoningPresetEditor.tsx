import type { CompanyModel, CompanyPreset } from '@paa/api-contracts'
import { AutoTextarea } from '@web/components/AutoTextarea'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { validateCompanyParameters } from '@web/features/model-services/utils/service-drafts'
import type * as React from 'react'

export function ReasoningPresetEditor({
  preset,
  model,
  setPreset,
  presetJson,
  updateModel,
  setError,
  setPresetJson,
  error,
}: {
  preset: CompanyPreset | null
  model: CompanyModel | undefined
  setPreset: React.Dispatch<React.SetStateAction<CompanyPreset | null>>
  presetJson: string
  updateModel: (next: CompanyModel) => void | undefined
  setError: React.Dispatch<React.SetStateAction<string | Error>>
  setPresetJson: React.Dispatch<React.SetStateAction<string>>
  error: string | Error
}) {
  return (
    <>
      {preset && model && (
        <Modal title="推理预设" onClose={() => setPreset(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              try {
                const value =
                  preset.mode === 'advanced'
                    ? validateCompanyParameters(JSON.parse(presetJson))
                    : validateCompanyParameters({ reasoning_effort: preset.value })
                const next = { ...preset, parameters: preset.mode === 'advanced' ? value : {} }
                updateModel({
                  ...model,
                  presets: [...model.presets.filter((p) => p.id !== preset.id), next],
                  selectedPresetId: preset.id,
                })
                setPreset(null)
              } catch (e) {
                setError(e as Error)
              }
            }}
          >
            <label>
              预设名称
              <input
                value={preset.name}
                required
                maxLength={80}
                onChange={(e) => setPreset({ ...preset, name: e.target.value })}
              />
            </label>
            <label>
              设置方式
              <select
                value={preset.mode}
                onChange={(e) =>
                  setPreset({ ...preset, mode: e.target.value as CompanyPreset['mode'] })
                }
              >
                <option value="simple">推理强度字符串</option>
                <option value="advanced">高级 JSON 参数</option>
              </select>
            </label>
            {preset.mode === 'simple' ? (
              <label>
                推理强度
                <input
                  value={preset.value}
                  required
                  maxLength={512}
                  placeholder="例如 high"
                  onChange={(e) => setPreset({ ...preset, value: e.target.value })}
                />
              </label>
            ) : (
              <details open>
                <summary>高级参数</summary>
                <label>
                  JSON 参数
                  <AutoTextarea
                    rows={3}
                    value={presetJson}
                    onChange={(e) => setPresetJson(e.target.value)}
                  />
                </label>
              </details>
            )}
            <ErrorNotice>{error}</ErrorNotice>
            <div className="form-actions">
              <button type="button" onClick={() => setPreset(null)}>
                取消
              </button>
              <button className="primary" type="submit">
                保存预设到草稿
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
