import type { Page } from '@paa/api-contracts'
import { useResource } from '@web/hooks/useResource'
import { filterParams, pageParams } from '@web/utils/list-state'
import { useEffect } from 'react'
import { useLocation, useSearchParams } from 'react-router'

export function useCursorPage<T, Extra = object>(endpoint: string | null) {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const boundaries = params.getAll('after')
  const cursor = boundaries.at(-1)
  const path = endpoint
    ? endpoint +
      (endpoint.includes('?') ? '&' : '?') +
      new URLSearchParams({ limit: '20', ...(cursor ? { cursor } : {}) })
    : null
  const resource = useResource<Page<T> & Extra>(path)
  const previous = () =>
    setParams(pageParams(params, 'previous'), { replace: true, state: location.state })
  useEffect(() => {
    // Deleting the final row can leave a page empty, including after returning
    // from its detail. Walk back to the nearest still-available page.
    if (resource.data && !resource.data.items.length && cursor) {
      setParams(pageParams(params, 'previous'), { replace: true, state: location.state })
    }
  }, [resource.data, cursor, params, setParams, location.state])
  return {
    ...resource,
    page: boundaries.length + 1,
    previous,
    next: () =>
      setParams(pageParams(params, 'next', resource.data?.nextCursor), { state: location.state }),
    params,
    filter: (values: Record<string, string>) =>
      setParams(filterParams(params, values), { replace: true, state: location.state }),
  }
}
