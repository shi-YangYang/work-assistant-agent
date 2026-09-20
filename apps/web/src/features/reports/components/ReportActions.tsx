import type { Report } from '@paa/api-contracts'
import { Actions } from '@web/components/Actions'
import { DeleteRecord } from '@web/features/records/components/DeleteRecord'
import { useWorkspace } from '@web/lib/workspace'
import { detailState } from '@web/utils/navigation'
import { useState } from 'react'
import { Link, useLocation } from 'react-router'

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
