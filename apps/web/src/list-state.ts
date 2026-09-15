import { useEffect } from 'react'
import { useLocation, useSearchParams } from 'react-router'
import type { Page } from '@paa/api-contracts'
import { useResource } from './api'

export function pageParams(
  params: URLSearchParams,
  direction: 'next' | 'previous',
  cursor?: string | null,
) {
  const next = new URLSearchParams(params)
  const boundaries = next.getAll('after')
  next.delete('after')
  if (direction === 'next' && cursor) boundaries.push(cursor)
  else if (direction === 'previous') boundaries.pop()
  for (const value of boundaries) next.append('after', value)
  return next
}
export function filterParams(params: URLSearchParams, values: Record<string, string>) {
  const next = new URLSearchParams(params)
  next.delete('after')
  for (const [key, value] of Object.entries(values)) {
    if (value) next.set(key, value)
    else next.delete(key)
  }
  return next
}
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
