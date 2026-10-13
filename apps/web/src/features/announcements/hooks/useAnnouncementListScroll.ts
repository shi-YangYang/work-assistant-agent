import { useEffect, useLayoutEffect, useRef } from 'react'
import { useLocation } from 'react-router'
import { epoch } from '@web/api/client'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'

// Navigation state is not unsaved user content. Each login gets a fresh cache;
// a departing old session cannot write back into the current session's cache.
let navigation: {
  generation: number
  scope: string
  positions: Map<string, number>
} | null = null

// List data may have expired while its detail was open. Restore only after the
// list has height again, rather than letting the initial loading view clamp it.
export function useAnnouncementListScroll(active: boolean, ready: boolean) {
  const { identity } = useWorkspace()
  const location = useLocation()
  const scope = identityScope(identity)
  const generation = epoch
  const key = location.pathname + location.search
  const listRef = useRef<HTMLDivElement>(null)
  const restore = useRef<{
    node: HTMLElement
    pending: boolean
    position: number
  } | null>(null)
  useLayoutEffect(() => {
    const node = listRef.current?.closest<HTMLElement>('[data-scroll-container]')
    if (!active || !node) return
    const freshSession = navigation?.generation !== generation || navigation.scope !== scope
    if (freshSession) navigation = { generation, scope, positions: new Map() }
    const cache = navigation!
    const saved = cache.positions.get(key)
    const state = {
      node,
      pending: typeof saved === 'number' || freshSession,
      position: typeof saved === 'number' ? saved : freshSession ? 0 : node.scrollTop,
    }
    restore.current = state
    const remember = () => {
      if (!state.pending) state.position = node.scrollTop
    }
    const cancel = (event: Event) => {
      if (
        event instanceof KeyboardEvent &&
        !['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)
      )
        return
      state.pending = false
      state.position = node.scrollTop
    }
    node.addEventListener('scroll', remember)
    node.addEventListener('wheel', cancel, { passive: true })
    node.addEventListener('touchmove', cancel, { passive: true })
    node.addEventListener('pointerdown', cancel)
    node.addEventListener('keydown', cancel)
    return () => {
      node.removeEventListener('scroll', remember)
      node.removeEventListener('wheel', cancel)
      node.removeEventListener('touchmove', cancel)
      node.removeEventListener('pointerdown', cancel)
      node.removeEventListener('keydown', cancel)
      if (navigation === cache && epoch === generation) cache.positions.set(key, state.position)
      restore.current = null
    }
  }, [active, key, scope, generation])
  useEffect(() => {
    const state = restore.current
    if (!active || !ready || !state?.pending) return
    state.node.scrollTop = state.position
    state.position = state.node.scrollTop
    state.pending = false
  }, [active, ready, key, scope, generation])
  return listRef
}
