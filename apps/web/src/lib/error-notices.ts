import type { ReactNode } from 'react'
import { createContext } from 'react'

export type NoticeContent = {
  children: ReactNode | Error
  retry?: () => void
  retryLabel?: string
  hint?: ReactNode
  className?: string
  actionsClassName?: string
  priority?: number
}

export type NoticeEntry = NoticeContent & {
  scope: string
  diagnostics: boolean
  supportLink: string | null
}

type Snapshot = { activeScope?: string; notices: NoticeEntry[] }

export function createNoticeStore() {
  const scopes = new Map<string, number>()
  const notices = new Map<string, NoticeEntry>()
  const listeners = new Set<() => void>()
  let snapshot: Snapshot = { notices: [] }
  const publish = () => {
    let activeScope: string | undefined
    let priority = -Infinity
    for (const [id, next] of scopes) {
      if (next >= priority) {
        activeScope = id
        priority = next
      }
    }
    snapshot = { activeScope, notices: [...notices.values()] }
    listeners.forEach((listener) => listener())
  }
  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    enter(id: string, priority: number) {
      scopes.set(id, priority)
      publish()
      return () => {
        scopes.delete(id)
        publish()
      }
    },
    set(id: string, notice: NoticeEntry) {
      const previous = notices.get(id)
      if (previous?.children !== notice.children) notices.delete(id)
      notices.set(id, notice)
      publish()
    },
    remove(id: string) {
      if (notices.delete(id)) publish()
    },
  }
}

export const ErrorNoticeContext = createContext<{
  store: ReturnType<typeof createNoticeStore>
  scope: string
  priority: number
  visibleScopes: string[]
  connectionMessage: string
} | null>(null)
