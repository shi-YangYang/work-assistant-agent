import { WorkDetail } from '@web/features/work/components/WorkDetail'
import { useLocation, useParams } from 'react-router'

export function WorkDetailPage() {
  const { id } = useParams()
  const location = useLocation()
  return <WorkDetail recordId={id} recordSearch={location.search} />
}
