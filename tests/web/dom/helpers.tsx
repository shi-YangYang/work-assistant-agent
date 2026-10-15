import type { Identity } from '@paa/api-contracts'
import type { ReactNode } from 'react'
import { useMemo, useSyncExternalStore } from 'react'
import { vi } from 'vitest'
import { SessionDrafts } from '../../../apps/web/src/lib/session-drafts'
import { Workspace } from '../../../apps/web/src/lib/workspace'

export const identity = {
  company: { id: 'company', name: 'Company' },
  member: { id: 'owner', name: 'Owner', username: 'owner', role: 'employee', active: true },
} as Identity
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
export function createVault(account = identity) {
  const vault = new SessionDrafts({ suspend: (drafts) => drafts, release: () => {} })
  vault.resume(account)
  return vault
}
export function TestWorkspace({
  children,
  vault,
  account = identity,
}: {
  children: ReactNode
  vault: SessionDrafts
  account?: Identity
}) {
  const drafts = useSyncExternalStore(vault.subscribe, vault.getSnapshot)
  const setDraft = useMemo(() => vault.writer(), [vault, account])
  return (
    <Workspace
      value={{
        identity: account,
        drafts,
        setDraft,
        notify: vi.fn(),
        lastConversationId: null,
        rememberConversation: vi.fn(),
      }}
    >
      {children}
    </Workspace>
  )
}
export function dialogs() {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as typeof ResizeObserver
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
}
