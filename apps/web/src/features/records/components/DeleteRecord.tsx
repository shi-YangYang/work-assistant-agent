import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { deleteRecord, deletionImpactPath } from '@web/features/records/api/requests'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { useState } from 'react'

export function DeleteRecord({
  kind,
  id,
  title,
  revision,
  onClose,
  onDeleted,
}: {
  kind: 'work-items' | 'reports'
  id: string
  title: string
  revision: number
  onClose: () => void
  onDeleted: () => void
}) {
  const { identity, setDraft, notify } = useWorkspace()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const impact = useResource<{ messages: number; attachments: number; revision: number }>(
    deletionImpactPath(kind, id),
  )
  return (
    <Modal title={kind === 'reports' ? '删除报告' : '删除工作'} onClose={() => !busy && onClose()}>
      <p>确定删除“{title}”？此操作不能撤销。</p>
      {kind === 'work-items' ? (
        <p>原始消息和已提交报告中的工作记录会保留。</p>
      ) : identity.member.role === 'admin' ? (
        <p>
          同时删除关联的 {impact.data?.messages ?? '…'} 条原始消息与{' '}
          {impact.data?.attachments ?? '…'}{' '}
          个附件。其他已确认工作和报告保留，对应来源将标记为已删除。
        </p>
      ) : (
        <p>删除后不会自动重新生成该周期报告，原始消息和工作记录保留。</p>
      )}
      <ErrorNotice retry={impact.error ? impact.refresh : undefined}>
        {error || impact.error}
      </ErrorNotice>
      <div className={layoutStyles['form-actions']}>
        <button disabled={busy} onClick={onClose}>
          取消
        </button>
        <BusyButton
          className={controlsStyles['danger']}
          busy={busy}
          disabled={kind === 'reports' && !impact.data}
          onClick={async () => {
            setBusy(true)
            try {
              await deleteRecord(kind, id, { expectedRevision: impact.data?.revision ?? revision })
              setDraft(`${kind === 'reports' ? 'report' : 'work'}:${id}`, undefined)
              notify('已删除')
              onDeleted()
              window.dispatchEvent(new Event('paa-record-updated'))
            } catch (e) {
              setError(e as Error)
            } finally {
              setBusy(false)
            }
          }}
        >
          确认删除
        </BusyButton>
      </div>
    </Modal>
  )
}
