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
import { purposeNames, supportsPurpose } from '@web/features/model-services/types'
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
  const stored = (drafts.modelRouting as ModelRouting) || initial
  const legacyReport = stored?.report
  const value = stored && {
    ...stored,
    assistant:
      stored.assistant ||
      (legacyReport && typeof legacyReport === 'object'
        ? { serviceId: legacyReport.serviceId, modelId: legacyReport.modelId }
        : null),
    report: 'follow' as const,
  }
  const { busy, submit } = useDraftSubmission('modelRouting')
  const [error, setError] = useState<Error | string>('')
  const [conflict, setConflict] = useState(false)
  const [recovering, setRecovering] = useState(false)
  if (!value) return <p>正在读取用途…</p>
  if (
    [value.assistant, value.asr, value.image].some(
      (choice) => choice && typeof choice === 'object' && 'presetId' in choice,
    )
  )
    return (
      <section>
        <p>
          旧版用途草稿包含已移除的推理预设，无法直接保存。读取当前配置将放弃这份未保存的用途草稿，已保存的配置不受影响。
        </p>
        <ErrorNotice>{error}</ErrorNotice>
        <BusyButton
          busy={recovering}
          onClick={async () => {
            setRecovering(true)
            setError('')
            try {
              setDraft('modelRouting', await readModelRouting())
            } catch (issue) {
              setError(issue as Error)
            } finally {
              setRecovering(false)
            }
          }}
        >
          放弃旧草稿并读取当前配置
        </BusyButton>
      </section>
    )

  const change = (purpose: Exclude<Purpose, 'report'>, choice: ModelSelection | null) => {
    setDraft('modelRouting', { ...value, [purpose]: choice })
    setError('')
  }
  return (
    <section
      className={`${layoutStyles['sectioned-panel']} ${layoutStyles['settings-sections']} ${modelServicesStyles['model-routing']}`}
    >
      {(['assistant', 'asr', 'image'] as const).map((purpose) => {
        const choice = value[purpose]
        const options = services.flatMap((service) =>
          service.models
            .filter((m) => supportsPurpose(m.protocol, purpose))
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
            status={selected ? `${selected.service.name} · ${selected.model.model}` : '未配置'}
            defaultOpen={purpose === 'assistant'}
          >
            <div className={modelServicesStyles['routing-fields']}>
              <label>
                使用的模型
                <select
                  disabled={busy}
                  value={choice ? `${choice.serviceId}/${choice.modelId}` : ''}
                  onChange={(e) => {
                    const option = options.find(
                      (x) => `${x.service.id}/${x.model.id}` === e.target.value,
                    )
                    change(
                      purpose,
                      option
                        ? {
                            serviceId: option.service.id,
                            modelId: option.model.id,
                          }
                        : null,
                    )
                  }}
                >
                  <option value="">未配置</option>
                  {options.map(({ service, model }) => (
                    <option key={`${service.id}/${model.id}`} value={`${service.id}/${model.id}`}>
                      {service.name} · {model.model}
                    </option>
                  ))}
                </select>
              </label>
              {purpose === 'assistant' && (
                <p className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}>
                  聊天搭子和周报生成共用此模型。聊天可单独选择思考强度，报告使用模型的初始强度。
                </p>
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
                    asr: value.asr,
                    image: value.image,
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
