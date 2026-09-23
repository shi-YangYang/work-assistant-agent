import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import type * as React from 'react'

export function RemoveServiceDialog({
  removeOpen,
  draft,
  busy,
  setRemoveOpen,
  error,
  remove,
}: {
  removeOpen: boolean
  draft: ServiceDraft | undefined
  busy: string
  setRemoveOpen: React.Dispatch<React.SetStateAction<boolean>>
  error: string | Error
  remove: () => Promise<void>
}) {
  return (
    <>
      {removeOpen && draft && (
        <Modal
          title={draft.revision ? '删除模型服务' : '丢弃服务草稿'}
          onClose={() => {
            if (!busy) setRemoveOpen(false)
          }}
        >
          <p>
            {draft.revision
              ? '删除后，旧任务将无法继续使用这个服务，历史工作和报告会保留。'
              : '丢弃后，这份服务草稿和其中尚未保存的密钥将被清除。'}
          </p>
          <ErrorNotice>{error}</ErrorNotice>
          <div className={layoutStyles['form-actions']}>
            <button disabled={!!busy} onClick={() => setRemoveOpen(false)}>
              继续编辑
            </button>
            <BusyButton
              className={controlsStyles['danger']}
              busy={busy === 'delete'}
              disabled={!!busy}
              onClick={() => void remove()}
            >
              {draft.revision ? '确认删除服务' : '丢弃草稿'}
            </BusyButton>
          </div>
        </Modal>
      )}
    </>
  )
}
