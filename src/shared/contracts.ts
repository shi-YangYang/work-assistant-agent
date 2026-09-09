export const CHANNELS = {
  status: 'paa:status',
  retry: 'paa:retry',
  meetings: 'paa:meetings',
  meeting: 'paa:meeting',
  recordingStatus: 'paa:recording-status',
  recordingStart: 'paa:recording-start',
  recordingStop: 'paa:recording-stop',
  statusChanged: 'paa:status-changed',
  lifecycleError: 'paa:lifecycle-error',
} as const
export type Capability = { id: 'recording' | 'transcription' | 'summary'; available: boolean }
export type CoreStatus = {
  connection: 'starting' | 'ready' | 'error' | 'stopped'
  message: string
  pythonVersion?: string
  processId?: number
  capabilities: Capability[]
  storageError?: string | null
}
export type MeetingState =
  'starting' | 'recording' | 'stopping' | 'completed' | 'interrupted' | 'failed'
export type Meeting = {
  id: string
  title: string
  createdAt: string
  startedAt: string | null
  endedAt: string | null
  status: MeetingState
  durationMs: number
  errorCode: string | null
  deviceName: string | null
  sampleRate: number
  channels: number
  sampleWidth: number
  frames: number
  bytes: number
  format: 'wav'
  audioAvailable: boolean
  audioError: string | null
}
export type RecordingStatus = {
  meetingId: string | null
  state: MeetingState | 'idle'
  elapsedMs: number
  deviceName: string | null
  inputLevel: number
  error: { code: string; message: string } | null
}
export type Result<T> = { ok: true; value: T } | { ok: false; message: string; code?: string }
export type MeetingsResult =
  { ok: true; meetings: Meeting[]; hasMore: boolean } | { ok: false; message: string }
export interface DesktopApi {
  getStatus(): Promise<CoreStatus>
  retryCore(): Promise<CoreStatus>
  listMeetings(offset?: number): Promise<MeetingsResult>
  getMeeting(meetingId: string): Promise<Result<Meeting>>
  getRecordingStatus(): Promise<Result<RecordingStatus>>
  startRecording(operationId: string): Promise<Result<RecordingStatus>>
  stopRecording(meetingId: string): Promise<Result<RecordingStatus>>
  onStatusChanged(listener: (status: CoreStatus) => void): () => void
  onLifecycleError(listener: (message: string) => void): () => void
}
export const UNAVAILABLE_CAPABILITIES: Capability[] = [
  { id: 'recording', available: false },
  { id: 'transcription', available: false },
  { id: 'summary', available: false },
]
export const ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
export const ACTIVE_STATES: string[] = ['starting', 'recording', 'stopping']
