import type { Deliverable, DeliverableSummary } from '@paa/api-contracts'
import { useResource } from '@web/hooks/useResource'
import { deliverablePath } from '../api/deliverables'
import { useState } from 'react'

export function useDeliverable(item: DeliverableSummary) {
  const [revision, setRevision] = useState(item.revision)
  const resource = useResource<Deliverable>(deliverablePath(item.id, revision))
  return { ...resource, revision, setRevision }
}
