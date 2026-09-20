import { ReportDetail } from '@web/features/reports/components/ReportDetail'
import { WorkDetail } from '@web/features/work/components/WorkDetail'
import { Navigate, useLocation, useParams } from 'react-router'

import { TeamWorkspace as Workspace } from '@web/features/team/components/TeamWorkspace'

export function TeamWorkspace() {
  return (
    <Workspace
      renderDetail={(view, id, revision, onDeleted) =>
        view === 'work' ? (
          <WorkDetail
            key={`${id}:${revision}`}
            recordId={id}
            recordSearch={revision ? `?revision=${revision}` : ''}
          />
        ) : (
          <ReportDetail
            key={`${id}:${revision}`}
            recordId={id}
            recordSearch={revision ? `?revision=${revision}` : ''}
            onRecordDeleted={onDeleted}
          />
        )
      }
    />
  )
}

// Existing bookmarks and source links keep working, but enter the same workspace.
export function TeamLegacyRedirect() {
  const location = useLocation()
  const { id } = useParams()
  const params = new URLSearchParams(location.search)
  const reports =
    location.pathname === '/team/reports' ||
    params.get('tab') === 'reports' ||
    params.get('metric') === 'reports'
  params.set('view', reports ? 'reports' : 'work')
  if (id) params.set('member', id)
  if (params.get('metric') === 'blocked') params.set('workStatus', 'blocked')
  if (/^\d{4}-\d{2}-\d{2}$/.test(params.get('period') || '')) {
    params.set('start', params.get('period')!)
    params.set('end', params.get('period')!)
    params.set('period', 'custom')
  }
  params.delete('tab')
  params.delete('metric')
  return <Navigate to={`/team?${params}`} replace />
}
