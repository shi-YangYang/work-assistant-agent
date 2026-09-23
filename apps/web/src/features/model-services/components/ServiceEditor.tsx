import controlsStyles from '../../../styles/controls.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import modelServicesStyles from '../styles/model-services.module.css'
import { BusyButton } from '@web/components/BusyButton'
import { ConflictRecovery } from '@web/components/ConflictRecovery'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { readModelService } from '@web/features/model-services/api/requests'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { cleanServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { ArrowLeft, ArrowRight, Cpu, Trash2 } from 'lucide-react'
import type * as React from 'react'

export function ServiceEditor({
  busy,
  select,
  dirty,
  draft,
  setRemoveOpen,
  update,
  setKeys,
  connectionReady,
  error,
  conflict,
  save,
  setAssignServiceId,
  setTab,
  children,
}: {
  busy: string
  select: (id: string | null) => void
  dirty: boolean
  draft: ServiceDraft
  setRemoveOpen: (open: boolean) => void
  update: (draft: ServiceDraft) => void
  setKeys: React.Dispatch<React.SetStateAction<Record<string, string>>>
  connectionReady: boolean
  error: string | Error
  conflict: boolean
  save: (target?: ServiceDraft, assign?: boolean) => Promise<boolean>
  setAssignServiceId: (id: string) => void
  setTab: (tab: 'services' | 'routing') => void
  children: React.ReactNode
}) {
  return (
    <div className={modelServicesStyles['service-detail']}>
      <section
        className={`${layoutStyles['sectioned-panel']} ${modelServicesStyles['model-editor']}`}
        key={draft.id}
      >
        <header className={modelServicesStyles['model-editor-heading']}>
          <span className={modelServicesStyles['editor-service-symbol']} aria-hidden="true">
            <Cpu size={24} />
          </span>
          <div className={modelServicesStyles['editor-service-name']}>
            <h3>{draft.name || '新服务'}</h3>
            <span className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}>
              {draft.models.length} 个模型
            </span>
          </div>
          <span className={modelServicesStyles['service-save-state']} data-changed={dirty}>
            {dirty ? '有未保存的更改' : '已保存'}
          </span>
          <button
            className={controlsStyles['icon-button']}
            aria-label="全部服务"
            title="全部服务"
            disabled={!!busy}
            onClick={() => select(null)}
          >
            <ArrowLeft size={16} />
          </button>
          <button
            className={`${controlsStyles['icon-button']} ${controlsStyles['danger']}`}
            aria-label={draft.revision ? '删除当前模型服务' : '丢弃草稿'}
            title={draft.revision ? '删除当前模型服务' : '丢弃草稿'}
            disabled={!!busy}
            onClick={() => setRemoveOpen(true)}
          >
            <Trash2 size={17} />
          </button>
        </header>
        {children}
        <div className={modelServicesStyles['model-editor-feedback']}>
          <ErrorNotice>{error}</ErrorNotice>
          {conflict && draft.revision > 0 && (
            <ConflictRecovery
              load={() => readModelService(draft)}
              render={(latest) => (
                <p>
                  {latest.name} · 版本 {latest.revision}
                </p>
              )}
              keep={(latest) =>
                update({ ...draft, revision: latest.revision, hasKey: latest.hasKey })
              }
              replace={(latest) => {
                update(cleanServiceDraft(latest))
                setKeys((previous) => ({ ...previous, [draft.id]: '' }))
              }}
            />
          )}
        </div>
        <footer className={modelServicesStyles['model-savebar']}>
          <span className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}>
            {dirty
              ? '保存后生效'
              : draft.models.length
                ? '选择各项功能使用的模型'
                : '添加模型后可设置用途'}
          </span>
          <button disabled={!!busy || !connectionReady} onClick={() => void save()}>
            保存服务
          </button>
          <BusyButton
            className={`${controlsStyles['primary']} ${modelServicesStyles['slot-primary']}`}
            busy={busy === 'save'}
            disabled={!!busy || !connectionReady || !draft.models.length}
            onClick={() => {
              if (dirty) void save(draft, true)
              else {
                setAssignServiceId('')
                setTab('routing')
              }
            }}
          >
            {dirty ? '保存并设置用途' : '设置用途'} <ArrowRight size={15} />
          </BusyButton>
        </footer>
      </section>
    </div>
  )
}
