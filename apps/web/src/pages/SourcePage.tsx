import type { WorkMessage } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { messagePath } from '@web/features/assistant/api/requests'
import { MessageCard } from '@web/features/assistant/components/MessageCard'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { detailReturn } from '@web/utils/navigation'
import { useLocation, useParams } from 'react-router'

export function SourcePage() {
  const { id } = useParams()
  const { identity } = useWorkspace()
  const { data, error, refresh } = useResource<WorkMessage>(messagePath(id), 2000)
  const location = useLocation()
  const context = detailReturn(location.pathname, location.state)
  return (
    <div className="page narrow">
      <div className="page-heading">
        <div>
          <h2>原始上报</h2>
          <p>来源：{context.label}</p>
        </div>
      </div>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data && (
        <MessageCard message={data} own={data.ownerId === identity.member.id} onChange={refresh} />
      )}
    </div>
  )
}
