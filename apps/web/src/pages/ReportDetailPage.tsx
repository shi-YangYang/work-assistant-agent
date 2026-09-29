import { ReportDetail } from '@web/features/reports/components/detail/ReportDetail'
import { useLocation, useParams } from 'react-router'

export function ReportDetailPage() {
  const { id } = useParams()
  const location = useLocation()
  return <ReportDetail recordId={id} recordSearch={location.search} />
}
