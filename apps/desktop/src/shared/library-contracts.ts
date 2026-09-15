import type { Meeting, Result } from './contracts'
export type MeetingQuery = { text: string; from: string | null; to: string | null; offset: number }
export type MeetingHit =
  | { source: 'title'; text: string }
  | { source: 'transcript'; text: string; segmentId: string; startMs: number }
  | { source: 'summary'; text: string; locator: string; generatedAt: string }
export type LibraryPage = {
  items: { meeting: Meeting; hit: MeetingHit | null }[]
  hasMore: boolean
}
export type ExportOptions = {
  format: 'md' | 'txt'
  scope: 'summary' | 'transcript' | 'both'
  timestamps: boolean
}
export type LibraryOperation<T> = {
  state: 'queued' | 'running' | 'completed' | 'failed'
  value: T | null
  error: { code: string; message: string } | null
}
export type SnapshotInfo = { bytes: number; title: string; date: string }
export type SnapshotChunk = { data: string; nextOffset: number; done: boolean }
export interface LibraryApi {
  queryMeetings(query: MeetingQuery): Promise<Result<LibraryPage>>
  renameMeeting(id: string, title: string): Promise<Result<Meeting>>
  deleteMeeting(id: string): Promise<Result<{ deleted: boolean }>>
  copyMinutes(id: string): Promise<Result<{ copied: boolean }>>
  exportMeeting(id: string, options: ExportOptions): Promise<Result<{ canceled: boolean }>>
}
