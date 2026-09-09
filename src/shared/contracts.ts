export const CHANNELS = {
  status: 'paa:status',
  retry: 'paa:retry',
  meetings: 'paa:meetings',
  statusChanged: 'paa:status-changed',
} as const

export type Capability = {
  id: 'recording' | 'transcription' | 'summary'
  available: boolean
}

export type CoreStatus = {
  connection: 'starting' | 'ready' | 'error' | 'stopped'
  message: string
  pythonVersion?: string
  processId?: number
  capabilities: Capability[]
}

export type Meeting = { id: string; title: string; createdAt: string }

export type MeetingsResult = { ok: true; meetings: Meeting[] } | { ok: false; message: string }

export interface DesktopApi {
  getStatus(): Promise<CoreStatus>
  retryCore(): Promise<CoreStatus>
  listMeetings(): Promise<MeetingsResult>
  onStatusChanged(listener: (status: CoreStatus) => void): () => void
}

export const UNAVAILABLE_CAPABILITIES: Capability[] = [
  { id: 'recording', available: false },
  { id: 'transcription', available: false },
  { id: 'summary', available: false },
]
