export type CompanyRequest = {
  action: 'status' | 'login' | 'cancel' | 'sync' | 'logout' | 'clear'
}
export type CompanyIdentity = {
  member: { id: string; name: string; role: 'admin' | 'employee' }
  company: { id: string; name: string }
}
export type VoiceprintStatus = {
  enabled: boolean
  profileCount: number
  modelId: string
  state: 'disabled' | 'ready' | 'processing' | 'failed'
  error: string | null
}
export type CompanyStatus = {
  serverUrl: string
  session: 'guest' | 'authorizing' | 'signed-in' | 'expired'
  identity: CompanyIdentity | null
  busy: boolean
  error: string | null
  syncedAt: string | null
  profileCount: number
  engine: VoiceprintStatus | null
}
export function validCompanyRequest(input: unknown): input is CompanyRequest {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return false
  const value = input as Record<string, unknown>
  return (
    Object.keys(value).join() === 'action' &&
    ['status', 'login', 'cancel', 'sync', 'logout', 'clear'].includes(String(value.action))
  )
}
