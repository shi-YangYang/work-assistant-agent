import type { QueryResource } from '@web/lib/query-resource'
import { useEffect, useSyncExternalStore } from 'react'

const empty = { data: null, error: '', loading: false }
const noSubscription = () => () => {}
const emptySnapshot = () => empty

export function useQueryResource<T>(resource: QueryResource<T> | null) {
  const snapshot = useSyncExternalStore(
    resource?.subscribe ?? noSubscription,
    resource?.getSnapshot ?? emptySnapshot,
  )
  useEffect(() => {
    void resource?.ensure()
  }, [resource])
  return {
    ...snapshot,
    refresh: resource?.refresh ?? (() => Promise.resolve()),
    invalidate: resource?.invalidate ?? (() => Promise.resolve()),
  }
}
