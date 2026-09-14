import { createContext, useContext } from 'react'
import type { Identity } from '../shared/company-contracts'

export interface DraftStore {
  [key: string]: unknown
}
interface WorkspaceState {
  identity: Identity
  drafts: DraftStore
  setDraft: (key: string, value: unknown) => void
  notify: (value: string) => void
}
// Keep identity in a module separate from frequently refreshed UI components.
export const Workspace = createContext<WorkspaceState | null>(null)
export function useWorkspace() {
  const workspace = useContext(Workspace)
  if (!workspace) throw new Error('工作页面缺少 Workspace Provider')
  return workspace
}
