import type { CompanyRequest, CompanyStatus } from './company-contracts'
import type { SpeakerRequest, SpeakerStatus } from './speaker-contracts'
import type { LibraryApi } from './library-contracts'
import type {
  ServiceList,
  ServiceProfile,
  ServiceDraft,
  ModelOperation,
  SummaryView,
  SummarySource,
} from './summary-contracts'
export const CHANNELS = {
  company: 'paa:company',
  companyChanged: 'paa:company-changed',
  speakers: 'paa:speakers',
  library: 'paa:library',
  summarySettings: 'paa:summary-settings',
  summaryGet: 'paa:summary-get',
  summaryGenerate: 'paa:summary-generate',
  summarySource: 'paa:summary-source',
  modelManage: 'paa:model-manage',
  inferenceDevice: 'paa:inference-device',
  transcriptionRerun: 'paa:transcription-rerun',
  modelStatus: 'paa:model-status',
  modelDownload: 'paa:model-download',
  modelCancel: 'paa:model-cancel',
  transcriptionStart: 'paa:transcription-start',
  transcriptionStatus: 'paa:transcription-status',
  transcript: 'paa:transcript',
  status: 'paa:status',
  retry: 'paa:retry',
  meetings: 'paa:meetings',
  meeting: 'paa:meeting',
  recordingStatus: 'paa:recording-status',
  recordingStart: 'paa:recording-start',
  recordingStop: 'paa:recording-stop',
  recordingPause: 'paa:recording-pause',
  recordingResume: 'paa:recording-resume',
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
  | 'starting'
  | 'recording'
  | 'pausing'
  | 'paused'
  | 'resuming'
  | 'stopping'
  | 'completed'
  | 'interrupted'
  | 'failed'
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
  deleting?: boolean
  deletionError?: string | null
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
export interface DesktopApi extends LibraryApi {
  company(input: CompanyRequest): Promise<CompanyStatus>
  onCompanyChanged(listener: (status: CompanyStatus) => void): () => void
  speakers(input: SpeakerRequest): Promise<Result<SpeakerStatus>>
  listModelServices(): Promise<Result<ServiceList>>
  getModelService(id: string): Promise<Result<ServiceProfile>>
  saveModelService(draft: ServiceDraft): Promise<Result<ServiceList>>
  removeModelService(id: string): Promise<Result<ServiceList>>
  selectModelService(id: string | null): Promise<Result<ServiceList>>
  setAutomaticSummary(value: boolean): Promise<Result<ServiceList>>
  requestModels(draft: ServiceDraft): Promise<Result<{ id: string }>>
  checkModel(draft: ServiceDraft): Promise<Result<{ id: string }>>
  getModelOperation(id: string, offset?: number): Promise<Result<ModelOperation>>
  getSummary(meetingId: string): Promise<Result<SummaryView>>
  generateSummary(meetingId: string): Promise<Result<SummaryView>>
  getSummarySource(meetingId: string, segmentId: string): Promise<Result<SummarySource>>
  manageTranscriptionModel(
    action: 'download' | 'cancel' | 'configure' | 'remove',
    id: string,
    language?: TranscriptionLanguage,
  ): Promise<Result<ModelState>>
  setTranscriptionDevice(device: 'cpu' | 'gpu'): Promise<Result<ModelState>>
  rerunTranscription(
    meetingId: string,
    modelId: string,
    language: TranscriptionLanguage,
  ): Promise<Result<TranscriptionStatus>>
  cancelRetranscription(meetingId: string): Promise<Result<TranscriptionStatus>>
  getTranscriptionModel(): Promise<Result<ModelState>>
  downloadTranscriptionModel(): Promise<Result<ModelState>>
  cancelModelDownload(): Promise<Result<ModelState>>
  startTranscription(meetingId: string): Promise<Result<TranscriptionStatus>>
  getTranscriptionStatus(meetingId: string): Promise<Result<TranscriptionStatus>>
  listTranscript(
    meetingId: string,
    cursor?: number,
    publication?: string,
  ): Promise<Result<TranscriptPage>>
  getStatus(): Promise<CoreStatus>
  retryCore(): Promise<CoreStatus>
  listMeetings(offset?: number): Promise<MeetingsResult>
  getMeeting(meetingId: string): Promise<Result<Meeting>>
  getRecordingStatus(): Promise<Result<RecordingStatus>>
  startRecording(operationId: string): Promise<Result<RecordingStatus>>
  pauseRecording(meetingId: string): Promise<Result<RecordingStatus>>
  resumeRecording(meetingId: string): Promise<Result<RecordingStatus>>
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
export const ACTIVE_STATES: string[] = [
  'starting',
  'recording',
  'pausing',
  'paused',
  'resuming',
  'stopping',
]

export type TranscriptionLanguage = 'zh' | 'en' | 'mixed'
export type ModelEntry = {
  id: string
  name: string
  parameters: number
  description: string
  occupiedBytes: number
  default: boolean
  deleteBlockedReason: string | null
} & ModelStateBase
export type ModelState = ModelStateBase & {
  device: 'cpu' | 'gpu'
  backend: 'ctranslate2' | 'mlx'
  hardware: {
    cpuName: string
    gpuNames: string[]
    gpuName: string | null
    gpuAvailable: boolean
    gpuBackend: 'mlx' | 'cuda' | null
    gpuReason: string | null
  }
  defaultModel: string
  language: TranscriptionLanguage
  preparingModel: string | null
  models: ModelEntry[]
}
export type ModelStateBase = {
  modelId: string
  revision: string
  state: 'missing' | 'downloading' | 'verifying' | 'ready' | 'error'
  downloadedBytes: number
  totalBytes: number
  requiredBytes: number
  source: string
  license: string
  error: string | null
}
export type TranscriptionStatus = {
  meetingId: string
  state: 'not_started' | 'queued' | 'running' | 'draining' | 'completed' | 'paused' | 'failed'
  processedMs: number
  audioMs: number
  pendingMs: number
  targetFrames: number | null
  error: string | null
  sourceIncomplete: boolean
  candidate: boolean
  actual: TranscriptionSnapshot | null
  published: TranscriptionSnapshot | null
  publication: string
  canContinue: boolean
  continuationBlockedReason: string | null
}
export type TranscriptionSnapshot = {
  device?: 'cpu' | 'gpu'
  modelId: string
  revision: string
  language: TranscriptionLanguage
  configVersion: number
}
export type TranscriptSegment = {
  id: string
  meetingId: string
  chunkId: string
  sequence: number
  startMs: number
  endMs: number
  text: string
  speaker: string | null
  speakerName?: string | null
  confidence: number | null
}
export type TranscriptPage = {
  segments: TranscriptSegment[]
  nextCursor: number
  hasMore: boolean
  publication?: string
}
