export type Role = 'admin' | 'employee'
export type Theme = 'system' | 'light' | 'dark'
export interface Member {
  id: string
  name: string
  username: string
  role: Role
  active: boolean
  mustChangePassword: boolean
}
export interface Identity {
  member: Member
  csrf: string
  company: { id: string; name: string }
}
export interface Attachment {
  id: string
  kind: 'image' | 'audio'
  name: string
  size: number
  mime: string
  duration: number | null
  url: string
}
export interface Progress {
  title: string
  summary: string
  status: 'in_progress' | 'blocked' | 'done'
  blocker: string
  nextStep: string
}
export interface Work extends Progress {
  id: string
  ownerId: string
  revision: number
  updatedAt: string
  history?: {
    id: string
    revision: number
    content: Progress
    sourceIds: string[]
    createdAt: string
  }[]
}
export interface Draft {
  id: string
  messageId: string
  workId: string | null
  baseRevision: number | null
  content: Progress
  status: 'pending' | 'confirmed' | 'ignored'
  revision: number
}
export interface Job {
  id: string
  kind: 'message' | 'report'
  targetId: string
  state: 'queued' | 'running' | 'awaiting_input' | 'succeeded' | 'failed' | 'awaiting_retry'
  phase: string
  error: string
  updatedAt: string
}
export interface WorkMessage {
  id: string
  ownerId: string
  text: string
  reply: string
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
}
export interface Rules {
  timezone: string
  daily: Schedule
  weekly: Schedule
  revision: number
}
export interface Team {
  items: { member: Member; work: Work[]; lastMessageAt: string | null; reportCount: number }[]
  updatedAt: string
}
export interface Page<T> {
  items: T[]
  nextCursor?: string | null
}
