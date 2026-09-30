import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import modelServicesStyles from '../styles/model-services.module.css'
import type { CompanyService, ModelRouting, ModelSelection } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ConflictRecovery } from '@web/components/forms/ConflictRecovery'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { PanelSection } from '@web/components/content/PanelSection'
import { readModelRouting, saveModelRouting } from '@web/features/model-services/api/requests'
import type { Purpose } from '@web/features/model-services/types'
import { purposeNames } from '@web/features/model-services/types'
import { useDraftSubmission } from '@web/hooks/useDraftSubmission'
import { useWorkspace } from '@web/lib/workspace'
import { useState } from 'react'

export function Routing({
  services,
  initial,
  refresh,
}: {
  services: CompanyService[]
  initial: ModelRouting | null
  refresh: () => void
}) {
  const { drafts, setDraft, notify } = useWorkspace()
  const value = (drafts.modelRouting as ModelRouting) || initial
  const { busy, submit } = useDraftSubmission('modelRouting')
  const [error, setError] = useState<Error | string>('')
  const [conflict, setConflict] = useState(false)
  if (!value) return <p>正在读取用途…</p>
  const change = (purpose: Purpose, choice: ModelSelection | 'follow' | null) => {
    setDraft('modelRouting', { ...value, [purpose]: choice })
    setError('')
  }
  return (
    <section
      className={`${layoutStyles['sectioned-panel']} ${modelServicesStyles['model-routing']}`}
    >
      {(['assistant', 'report', 'asr'] as const).map((purpose) => {
        const choice = value[purpose]
        const options = services.flatMap((service) =>
          service.models
            .filter((m) => (purpose === 'asr' ? m.protocol !== 'chat' : m.protocol === 'chat'))
            .map((model) => ({ service, model })),
        )
        const selected =
          typeof choice === 'object' && choice
            ? options.find(
                (x) => x.service.id === choice.serviceId && x.model.id === choice.modelId,
              )
            : null
        return (
          <PanelSection
            key={purpose}
            title={purposeNames[purpose]}
            status={
              choice === 'follow'
                ? '同工作助手'
                : selected
                  ? `${selected.service.name} · ${selected.model.model}`
                  : '未配置'
            }
            defaultOpen={purpose === 'assistant'}
          >
            <div className={modelServicesStyles['routing-fields']}>
              <label>
                使用的模型
                <select
                  disabled={busy}
                  value={
                    choice === 'follow'
                      ? 'follow'
                      : choice
                        ? `${choice.serviceId}/${choice.modelId}`
                        : ''
                  }
                  onChange={(e) => {
                    const option = options.find(
                      (x) => `${x.service.id}/${x.model.id}` === e.target.value,
                    )
                    change(
                      purpose,
                      e.target.value === 'follow'
                        ? 'follow'
                        : option
                          ? {
                              serviceId: option.service.id,
                              modelId: option.model.id,
                              presetId: option.model.selectedPresetId,
                              streaming: option.model.streaming,
                            }
                          : null,
                    )
                  }}
                >
                  <option value="">未配置</option>
                  {purpose === 'report' && <option value="follow">同工作助手</option>}
                  {options.map(({ service, model }) => (
                    <option key={`${service.id}/${model.id}`} value={`${service.id}/${model.id}`}>
                      {service.name} · {model.model}
                    </option>
                  ))}
                </select>
              </label>
              {choice === 'follow' && (
                <p className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}>
                  使用工作助手当前分配的模型、推理预设和请求方式。
                </p>
              )}
              {selected && typeof choice === 'object' && choice && purpose !== 'asr' && (
                <>
                  <label>
                    推理预设
                    <select
                      disabled={busy}
                      value={choice.presetId || ''}
                      onChange={(e) =>
                        change(purpose, { ...choice, presetId: e.target.value || null })
                      }
                    >
                      <option value="">服务默认</option>
                      {selected.model.presets.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label
                    className={`${layoutStyles['check-label']} ${modelServicesStyles['slot-check-label']}`}
                  >
                    <input
                      disabled={busy}
                      type="checkbox"
                      checked={choice.streaming}
                      onChange={(e) => change(purpose, { ...choice, streaming: e.target.checked })}
                    />
                    使用流式接口
                  </label>
                </>
              )}
            </div>
          </PanelSection>
        )
      })}
      <div className={layoutStyles['panel-footer']}>
        <ErrorNotice>{error}</ErrorNotice>
        {conflict && (
          <ConflictRecovery
            load={() => readModelRouting()}
            render={(latest) => <p>服务端用途版本 {latest.revision}</p>}
            keep={(latest) => {
              setDraft('modelRouting', { ...value, revision: latest.revision })
              setConflict(false)
            }}
            replace={(latest) => {
              setDraft('modelRouting', latest)
              setConflict(false)
            }}
          />
        )}
        <div
          className={`${layoutStyles['form-actions']} ${modelServicesStyles['slot-form-actions']} ${layoutStyles['editor-actions']}`}
        >
          <BusyButton
            className={`${controlsStyles['primary']} ${modelServicesStyles['slot-primary']}`}
            busy={busy}
            onClick={async () => {
              setError('')
              await submit(
                () =>
                  saveModelRouting({
                    assistant: value.assistant,
                    report: value.report,
                    asr: value.asr,
                    expectedRevision: value.revision,
                  }),
                () => {
                  refresh()
                  notify('用途分配已保存')
                },
                (error) => {
                  setError(error as Error)
                  setConflict(error instanceof ApiError && error.status === 409)
                },
              )
            }}
          >
            保存用途分配
          </BusyButton>
        </div>
      </div>
    </section>
  )
}
