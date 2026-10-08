export { default as inputRules } from '../input-rules.json'

export type Role = 'admin' | 'employee'
export type Theme = 'system' | 'light' | 'dark'
export interface Member {
  id: string
  name: string
  username: string
  role: Role
  active: boolean
  deleted?: boolean
  hasPassword: boolean
}
export interface MemberListItem extends Member {
  createdAt: string
}
export interface Identity {
  member: Member
  csrf: string
  company: { id: string; name: string }
}
export interface Attachment {
  workRevision?: number
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
export type ExecutionMode = 'ask' | 'auto' | 'full'
export interface ExecutionSettings {
  executionMode: ExecutionMode
  fullAccessConfirmed: boolean
  modeRevision: number
}
export interface AssistantContinuation {
  messageId: string
  jobId: string
  conversationId: string
}
export interface AssistantQuestion {
  id: string
  prompt: string
  type: 'single' | 'multiple' | 'text'
  options: { id: string; label: string; description?: string }[]
  allowCustom: boolean
}
export interface AssistantAnswer {
  questionId: string
  optionIds: string[]
  text: string
}
export interface AssistantInteraction {
  id: string
  messageId: string
  conversationId: string
  taskId: string
  revision: number
  state: 'waiting' | 'answered' | 'cancelled' | 'expired'
  questions: AssistantQuestion[]
  answers: AssistantAnswer[]
  createdAt: string
  continuation?: AssistantContinuation | null
}
export interface BusinessAction {
  confirmLabel?: string
  executionMode?: ExecutionMode
  continuation?: AssistantContinuation | null
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
  updateId?: string
  updateRevision?: number
  materialIds?: string[]
  title?: string
  details?: Partial<Progress & WorkRecordFields>
  changedFields?: string[]
  message?: string
  canConfirm?: boolean
  preview?: {
    materialNames?: Record<string, string>
    title: string
    content?: ReportContent
    before?: Record<string, unknown>
    changes?: Record<string, unknown>
    revision: number
  }
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
export type PersonaId = 'dabao' | 'professional'
export interface Conversation {
  executionMode?: ExecutionMode
  modeRevision?: number
  fullAccessConfirmed?: boolean
  personaId: PersonaId
  id: string
  title: string
  revision: number
  updatedAt: string
}
export interface WorkNode {
  type: string
  attrs?: Record<string, unknown>
  text?: string
  marks?: { type: string; attrs?: Record<string, unknown> }[]
  content?: WorkNode[]
}
export interface WorkDocument {
  schemaVersion: 1
  content: WorkNode[]
}
export interface WorkMaterialSource {
  attachmentId?: string
  deliverableId?: string
  revision?: number
  fileId?: string
}
export interface WorkMaterial {
  id: string
  workId: string
  revision: number
  attachment: Attachment
  createdAt: string
  removed: boolean
}
export interface WorkUpdate {
  id: string
  workId: string
  revision: number
  text: string
  materialIds: string[]
  origin: string
  ownerId: string
  createdAt: string
  updatedAt: string
  deleted: boolean
  workRevision: number
}
export interface WorkRecordFields {
  body?: WorkDocument
  bodyText?: string
  _changeKind?: string
  _updateText?: string
  _updateDeleted?: boolean
  materialIds?: string[]
}
export interface WorkPatch extends Partial<Omit<Progress, 'summary'>>, WorkRecordFields {
  expectedRevision: number
  materials?: WorkMaterialSource[]
}
export interface WorkUpdateInput {
  expectedRevision: number
  expectedUpdateRevision?: number
  text: string
  materialIds: string[]
  materials?: WorkMaterialSource[]
  status?: Progress['status']
  dueDate?: string | null
  blocker?: string
  nextStep?: string
}
export interface WorkWriteResult {
  work: Work
  materialIds: string[]
  update?: WorkUpdate
}
export interface WorkPageResult<T> {
  items: T[]
  nextCursor: number | null
}
export interface Work extends Progress, WorkRecordFields {
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
    content: Progress & WorkRecordFields
    origin?: 'manual' | 'assistant' | 'assistant_confirmed' | 'unknown'
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
export interface OperationFeedback {
  step: number
  action: string
  label: string
  state: 'failed' | 'conflict' | 'clarification' | 'waiting'
  message: string
}
export interface TaskNode {
  id: string
  parentId: string | null
  kind: 'model' | 'tool' | 'authorization' | 'review' | 'compaction'
  presentation?: { type: 'operation' | 'activity'; subject?: string }
  label: string
  state:
    | 'waiting'
    | 'running'
    | 'retry_wait'
    | 'succeeded'
    | 'failed'
    | 'awaiting_confirmation'
    | 'awaiting_input'
    | 'cancelled'
  attempts: number
  maxAttempts: number
  retries: number
  totalRetries: number
  round: number
  nextRetryAt: string | null
  errorCode: string
  error: string
  canRetry: boolean
}
export interface ContextUsage {
  jobId: string
  attempt: number
  fence: number
  seq: number
  model: string
  usedTokens: number
  contextWindow: number | null
  inputLimit: number | null
  outputReserve: number
  capacitySource: string
  thresholdRatio: number
  estimated: true
  state: 'ready' | 'compacting' | 'retry_wait' | 'failed'
  compactionId?: string | null
  beforeTokens?: number | null
  afterTokens?: number | null
  reason?: string | null
  updatedAt: string
}
export interface TaskOutcome {
  state:
    | 'processing'
    | 'completed'
    | 'partial'
    | 'needs_input'
    | 'needs_confirmation'
    | 'blocked'
    | 'cancelled'
  completed: string[]
  remaining: string[]
  reason?: string
  nextAction: 'none' | 'reply' | 'confirm' | 'retry'
}
export interface Job {
  replyStream?: ReplyStream | null
  taskOutcome?: TaskOutcome | null
  contextUsage?: ContextUsage | null
  incompleteTask?: boolean
  nodes?: TaskNode[]
  operationFeedback?: OperationFeedback[]
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
export interface DeliverableReference {
  id: string
  revision: number
  itemIds: string[]
}
export interface DeliverableFile {
  id: string
  name: string
  mimeType: string
  size: number
  url: string
}
export interface DeliverableSummary {
  id: string
  revision: number
  latestRevision: number
  title: string
  messageId: string
  itemCount: number
  updatedAt: string
  files?: DeliverableFile[]
}
export interface Deliverable extends DeliverableSummary {
  body: string
  items: { id: string; title: string; body: string }[]
  links: { itemId: string; workId: string; sourceRevision: number; unavailable: boolean }[]
}
export interface WorkReference {
  workId: string
}
export interface WorkReferenceView extends WorkReference {
  title?: string
  unavailable?: boolean
}
export interface WebReadSource {
  url: string
  title: string
  refetchFailed: boolean
}
export interface WorkMessage {
  replyStream?: ReplyStream | null
  workReference?: WorkReferenceView | null
  interactions?: AssistantInteraction[]
  deliverables?: DeliverableSummary[]
  actions?: BusinessAction[]
  conversationId: string | null
  id: string
  ownerId: string
  text: string
  reply: string
  citations?: DocumentCitation[]
  webSources?: WebReadSource[]
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
  ownerName?: string
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

export interface ReasoningOption {
  effort: string
}
export interface ReasoningReference {
  effort: string | null
  preferenceRevision: number
  configVersion: string
}
export interface ReasoningSettings {
  options: ReasoningOption[]
  selected: ReasoningOption | null
  preferenceRevision: number
  configVersion: string
}
export interface ModelReasoning {
  efforts: string[]
  initial: string | null
  parameterOverrides?: Record<string, Record<string, import('@paa/model-config').JsonValue>>
}
export interface ContextCapability {
  contextWindow: number | null
  inputLimit: number | null
  maxOutput: number | null
  source: string
}
export interface CompanyModel {
  contextWindow?: number | null
  contextCapability?: ContextCapability
  id: string
  model: string
  protocol: 'chat' | 'transcriptions' | 'qwen-asr' | 'dashscope-asr'
  protocolMode?: 'auto' | 'manual'
  reasoning: ModelReasoning
  parameters: Record<string, import('@paa/model-config').JsonValue>
  explicitReasoning?: boolean
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
  parameters?: Record<string, import('@paa/model-config').JsonValue> | null
  explicitReasoning?: boolean
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

export interface ReplyEvent {
  type: 'delta' | 'sync' | 'withdrawn'
  jobId: string
  attempt: number
  fence: number
  generation: number
  seq: number
  callId?: string
  state?: string
  text?: string
  delta?: string
}

export interface ReplyStream {
  version: 1
  generation: number
  state: 'streaming' | 'finalizing' | 'interrupted' | 'withdrawn'
  text: string
}

export interface JobFeedback {
  replyStream?: ReplyStream | null
  interactions?: AssistantInteraction[]
  taskOutcome?: TaskOutcome | null
  contextUsage?: ContextUsage | null
  incompleteTask?: boolean
  nodes?: TaskNode[]
  jobId: string
  attempt: number
  fence: number
  seq: number
  stage: string
  state: Job['state']
  text: string
  error: string
  updatedAt: string
  actions?: BusinessAction[]
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

export interface TeamWorkRow {
  id: string
  member: Member
  work: Work
}
export interface TeamReportRow {
  id: string
  member: Member
  kind: 'daily' | 'weekly'
  period: string
  periodEnd: string
  state: 'pending' | 'overdue' | 'submitted' | 'cancelled'
  scheduled: boolean
  deadlineAt: string | null
  timezone: string
  reportId: string | null
  revision: number | null
  submittedAt: string | null
  summary: string
}
export interface TeamWorkspacePage<T> extends Page<T> {
  total: number
  counts: Record<string, number>
  range: DateRange
  members: Member[]
}

export interface MemberDeletionImpact {
  voiceprints: number
  recordings: number
}

export interface VoiceprintCleanupSummary {
  legacy: MemberDeletionImpact & { members: number }
  pending: number
  failed: number
}

export interface AssistantMemory {
  enabled: boolean
  revision: number
  markdown: string
  updatedAt: string | null
  maxCharacters: number
}
