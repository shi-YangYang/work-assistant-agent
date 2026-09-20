import { BusyButton } from '@web/components/BusyButton'
import { ConflictRecovery } from '@web/components/ConflictRecovery'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { readModelService } from '@web/features/model-services/api/requests'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { cleanServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { ArrowLeft, ArrowRight, Trash2 } from 'lucide-react'
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
    <div className="service-detail">
      <div className="service-detail-toolbar">
        <button className="text-button" disabled={!!busy} onClick={() => select(null)}>
          <ArrowLeft size={16} /> 全部服务
        </button>
        <span className={`service-save-state${dirty ? ' changed' : ''}`}>
          {dirty ? '有未保存的更改' : '已保存'}
        </span>
      </div>
      <section className="sectioned-panel model-editor" key={draft.id}>
        <header className="model-editor-heading">
          <div>
            <h3>{draft.name || '新服务'}</h3>
            <span className="muted">{draft.models.length} 个模型</span>
          </div>
          <button
            className="icon-button danger"
            aria-label={draft.revision ? '删除当前模型服务' : '丢弃草稿'}
            title={draft.revision ? '删除当前模型服务' : '丢弃草稿'}
            disabled={!!busy}
            onClick={() => setRemoveOpen(true)}
          >
            <Trash2 size={17} />
          </button>
        </header>
        {children}
        <div className="model-editor-feedback">
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
        <footer className="model-savebar">
          <span className="muted">
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
            className="primary"
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
