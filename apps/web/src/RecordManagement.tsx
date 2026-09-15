import { useState } from 'react'
import { Link, useLocation } from 'react-router'
import type { Report } from '@paa/api-contracts'
import { useResource, write } from './api'
import { detailState } from './navigation'
import { useWorkspace } from './workspace'
import { Actions, BusyButton, ErrorNotice, Modal } from './ui'

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
  const [error, setError] = useState('')
  const impact = useResource<{ messages: number; attachments: number; revision: number }>(
    kind === 'reports' ? `/reports/${id}/deletion` : null,
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
      <div className="form-actions">
        <button disabled={busy} onClick={onClose}>
          取消
        </button>
        <BusyButton
          className="danger"
          busy={busy}
          disabled={kind === 'reports' && !impact.data}
          onClick={async () => {
            setBusy(true)
            try {
              await write(
                `/${kind}/${id}`,
                { expectedRevision: impact.data?.revision ?? revision },
                'DELETE',
              )
              setDraft(`${kind === 'reports' ? 'report' : 'work'}:${id}`, undefined)
              notify('已删除')
              onDeleted()
              window.dispatchEvent(new Event('paa-record-updated'))
            } catch (e) {
              setError((e as Error).message)
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

export function ReportActions({ report, onDeleted }: { report: Report; onDeleted: () => void }) {
  const { identity } = useWorkspace()
  const location = useLocation()
  const [deleting, setDeleting] = useState(false)
  const own = report.ownerId === identity.member.id && identity.member.role === 'employee'
  return (
    <>
      <Actions label="管理报告">
        {own && (
          <Link role="menuitem" to={`/reports/${report.id}?edit=1`} state={detailState(location)}>
            编辑报告
          </Link>
        )}
        {(identity.member.role === 'admin' || (own && !report.publishedRevision)) && (
          <button role="menuitem" className="danger" onClick={() => setDeleting(true)}>
            删除报告
          </button>
        )}
      </Actions>
      {deleting && (
        <DeleteRecord
          kind="reports"
          id={report.id}
          title={`${report.period}${report.kind === 'daily' ? '日报' : '周报'}`}
          revision={report.managementRevision ?? report.revision}
          onClose={() => setDeleting(false)}
          onDeleted={() => {
            setDeleting(false)
            onDeleted()
          }}
        />
      )}
    </>
  )
}
