export type Role = 'admin' | 'employee'
export type Theme = 'system' | 'light' | 'dark'
export interface Member {
  id: string
  name: string
  username: string
  role: Role
  active: boolean
  mustChangePassword: boolean
  hasPassword: boolean
}
export interface Identity {
  member: Member
  csrf: string
  company: { id: string; name: string }
}
export interface Attachment {
  id: string
  kind: 'image' | 'audio' | 'document'
  name: string
  size: number
  mime: string
  duration: number | null
  extraction?: {
    status: 'unsent' | 'pending' | 'processing' | 'ready' | 'partial' | 'failed'
    revision: number
    parserVersion: string
    error?: string
    warnings?: string[]
    scope?: string
    characters?: number
    chunks?: number
  } | null
  url: string
  previewUrl?: string | null
  image?: { width: number; height: number; warnings: string[] } | null
}
export interface DocumentCitation {
  attachmentId: string
  revision: number
  ordinal: number
  name: string
  location: string
}
export interface BusinessCitation {
  kind: 'business'
  token?: string
  unavailable?: boolean
  objectType?: 'work' | 'report' | 'message' | 'document' | 'member'
  objectId?: string
  ownerId?: string
  employeeName?: string
  employeeActive?: boolean
  title?: string
  revision?: number
  at?: string
  location?: string
}
export interface BusinessSource extends BusinessCitation {
  content: Record<string, string>
  currentRevision?: number
  period?: string
  periodEnd?: string
}
export interface ExtractionPage {
  attachment: Attachment
  items: { ordinal: number; location: string; text: string }[]
  nextCursor: number | null
}
export interface BusinessAction {
  id: string
  messageId: string
  action: string
  label: string
  state: 'pending' | 'running' | 'succeeded' | 'failed' | 'conflict' | 'cancelled' | 'unavailable'
  revision: number
  createdAt: string
  objectType?: 'work' | 'report'
  objectId?: string
  objectRevision?: number
  title?: string
  details?: Partial<Progress>
  message?: string
  canConfirm?: boolean
  preview?: { title: string; content?: ReportContent; revision: number }
  impact?: { messages: number; attachments: number }
  job?: Job
}
export interface Progress {
  dueDate?: string | null
  title: string
  summary: string
  status: 'in_progress' | 'blocked' | 'done'
  blocker: string
  nextStep: string
}
export interface Conversation {
  id: string
  title: string
  revision: number
  updatedAt: string
}
export interface Work extends Progress {
  origin?: 'manual' | 'assistant' | 'suggestion'
  historical?: boolean
  businessLinks?: BusinessCitation[]
  hasBusinessLinks?: boolean
  id: string
  ownerId: string
  revision: number
  updatedAt: string
  history?: {
    id: string
    revision: number
    content: Progress
    sourceIds: string[]
    deletedSourceIds?: string[]
    createdAt: string
  }[]
}
export interface Draft {
  businessLinks?: BusinessCitation[]
  id: string
  messageId: string
  workId: string | null
  baseRevision: number | null
  content: Progress
  status: 'pending' | 'confirmed' | 'ignored'
  revision: number
}
export interface Job {
  stage?: string
  attempt?: number
  fence?: number
  id: string
  kind: 'message' | 'report' | 'document'
  targetId: string
  state:
    | 'queued'
    | 'running'
    | 'awaiting_input'
    | 'succeeded'
    | 'failed'
    | 'awaiting_retry'
    | 'cancelled'
  phase: string
  error: string
  updatedAt: string
}
export interface WorkMessage {
  actions?: BusinessAction[]
  conversationId: string | null
  id: string
  ownerId: string
  text: string
  reply: string
  citations?: DocumentCitation[]
  businessCitations?: BusinessCitation[]
  businessUnavailable?: boolean
  replyTo: string | null
  transcript: string
  transcriptRevision: number
  createdAt: string
  attachments: Attachment[]
  drafts: Draft[]
  suggestions: { id: string; content: Progress; workId: string | null; status: string }[]
  job: Job | null
}
export interface ReportContent {
  completed: string
  ongoing: string
  blockers: string
  next: string
}
export interface Report {
  historical?: boolean
  id: string
  ownerId: string
  kind: 'daily' | 'weekly'
  period: string
  periodEnd: string
  timezone: string
  content: ReportContent
  candidate: { content: ReportContent; sourceIds: string[] } | null
  sourceIds: string[]
  revision: number
  publishedRevision: number
  managementRevision: number
  updatedAt: string
  job: Job | null
  revisions: {
    revision: number
    content: ReportContent
    sourceIds: string[]
    submittedAt: string
  }[]
}
export interface Schedule {
  enabled: boolean
  days: number[]
  generateTime: string
  deadline: string
  reminders?: boolean
  beforeMinutes?: number
}
export interface Rules {
  effectivePeriods?: Partial<Record<'daily' | 'weekly', string>>
  timezone: string
  daily: Schedule
  weekly: Schedule
  revision: number
}
export interface DateRange {
  period: string
  start: string
  end: string
  timezone: string
}
export interface TeamMetrics {
  reported: number
  members: number
  blocked: number
  reports: number
}
export interface Team {
  items: {
    member: Member
    work: Work[]
    workCount: number
    blockedCount: number
    lastMessageAt: string | null
    reportCount: number
  }[]
  metrics: TeamMetrics
  range: DateRange
  updatedAt: string
}
export interface TeamDetail {
  id: string
  member: Member
  title: string
  at: string
  href: string
  work?: Work
}
export interface Page<T> {
  items: T[]
  nextCursor?: string | null
}

export interface CompanyPreset {
  id: string
  name: string
  mode: 'simple' | 'advanced'
  value: string
  parameters: Record<string, import('@paa/model-config').JsonValue>
}
export interface CompanyModel {
  id: string
  model: string
  protocol: 'chat' | 'transcriptions' | 'qwen-asr' | 'dashscope-asr'
  protocolMode?: 'auto' | 'manual'
  presets: CompanyPreset[]
  selectedPresetId: string | null
  streaming: boolean
  language: string
}
export interface CompanyService {
  id: string
  name: string
  baseUrl: string
  models: CompanyModel[]
  revision: number
  hasKey: boolean
  updatedAt: string
}
export interface ModelSelection {
  serviceId: string
  modelId: string
  presetId: string | null
  streaming: boolean
}
export interface ModelRouting {
  revision: number
  source: 'environment' | 'database'
  assistant: ModelSelection | null
  report: ModelSelection | 'follow' | null
  asr: ModelSelection | null
  environment: {
    assistant: { baseUrl: string; model: string; hasKey: boolean }
    asr: { baseUrl: string; model: string; hasKey: boolean }
  } | null
}
export interface ModelCheck {
  draftVersion: string
  fingerprint: string
  service: string
  model: string
  revision: number
  purpose: 'assistant' | 'report' | 'asr'
  time: string
  elapsedMs: number
  checks: {
    name: string
    state: 'untested' | 'passed' | 'failed'
    message?: string
    code?: string
  }[]
  usage: Record<string, number> | null
  requestId: string
}

export interface JobFeedback {
  jobId: string
  attempt: number
  fence: number
  seq: number
  stage: string
  state: Job['state']
  text: string
  error: string
  updatedAt: string
}
export interface UsageRecord {
  id: string
  serviceId: string | null
  service: string | null
  model: string | null
  purpose: string
  state: string
  startedAt: string | null
  createdAt: string
  elapsedMs: number | null
  inputTokens: number | null
  outputTokens: number | null
  errorCode: string | null
  error: string | null
}
export interface ModelUsage extends Page<UsageRecord> {
  range: DateRange
  summary: {
    calls: number
    successRate: number | null
    states: Record<string, number>
    averageMs: number | null
    durationKnown: number
    inputTokens: number
    outputTokens: number
    inputKnown: number
    outputKnown: number
  }
  services: { id: string; name: string }[]
  models: string[]
}

export interface ReportObligation {
  id: string
  ownerId: string
  name: string | null
  kind: 'daily' | 'weekly'
  period: string
  periodEnd: string
  timezone: string
  deadlineAt: string
  state: 'pending' | 'overdue' | 'submitted' | 'cancelled'
  submittedAt: string | null
  reportId: string | null
  job?: Job | null
}
export interface ObligationPage extends Page<ReportObligation> {
  period: string | null
  counts: {
    expected: number
    submitted: number
    pending: number
    overdue: number
    cancelled: number
  }
}
export interface ReportNotification {
  id: string
  stage: 'ready' | 'due' | 'overdue'
  read: boolean
  updatedAt: string
  obligation: ReportObligation
}
export interface NotificationPage extends Page<ReportNotification> {
  unread: number
}

export interface SupportDiagnostics {
  occurredAt?: string | null
  page?: string | null
  category?:
    | 'network'
    | 'timeout'
    | 'unauthorized'
    | 'forbidden'
    | 'rate_limited'
    | 'server'
    | 'invalid_response'
    | 'conflict'
    | 'validation'
    | 'cancelled'
    | 'unknown'
    | null
  httpStatus?: number | null
  requestId?: string | null
  appVersion?: string | null
  browser?: string | null
  os?: string | null
  viewport?: string | null
}
export interface SupportFeedbackCreate {
  description: string
  diagnostics: SupportDiagnostics
}
export interface SupportFeedbackPatch {
  state: 'pending' | 'resolved'
  handlingNote: string
  expectedRevision: number
}
export interface SupportFeedback extends SupportFeedbackCreate {
  id: string
  ownerId: string
  ownerName: string
  state: 'pending' | 'resolved'
  handlingNote: string
  revision: number
  createdAt: string
  updatedAt: string
}

export interface LoginProviders {
  password: true
  dingtalk: boolean
}
export interface DingTalkConfiguration {
  corpId: string
  clientId: string
  hasSecret: boolean
  enabled: boolean
  revision: number
  callbackUrl: string
  verifiedAt: string | null
}
export interface DingTalkAccount {
  bound: boolean
  hasPassword: boolean
  available: boolean
  passwordVerified: boolean
}
