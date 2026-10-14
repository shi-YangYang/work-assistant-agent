import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react'
import { epoch } from '@web/api/client'
import { AssistantActivityStore, mountAssistantActivity } from '@web/api/assistant-activity'

export function useAssistantActivity(owner: string) {
  const generation = epoch
  const store = useMemo(() => new AssistantActivityStore(owner, generation), [owner, generation])
  useLayoutEffect(() => mountAssistantActivity(store), [store])
  return useSyncExternalStore(store.subscribe, store.getSnapshot)
}
