import type { MeetingQuery } from '../shared/library-contracts'
export function meetingQuery(text: string, from: string, to: string, offset = 0): MeetingQuery {
  function boundary(date: string, end: boolean): string | null {
    if (!date) return null
    const [year, month, day] = date.split('-').map(Number)
    const value = new Date(year, month - 1, day)
    if (
      !Number.isFinite(value.getTime()) ||
      value.getFullYear() !== year ||
      value.getMonth() !== month - 1 ||
      value.getDate() !== day
    )
      throw new Error('日期无效。')
    if (end) value.setDate(value.getDate() + 1)
    return value.toISOString()
  }
  if (from && to && from > to) throw new Error('开始日期不能晚于结束日期。')
  return { text: text.trim(), from: boundary(from, false), to: boundary(to, true), offset }
}
export class QueryGeneration {
  private version = 0
  private appliedQuery: MeetingQuery | null = null
  private paging = false
  next(): number {
    this.appliedQuery = null
    this.paging = false
    return ++this.version
  }
  current(version: number): boolean {
    return version === this.version
  }
  apply(version: number, query: MeetingQuery): boolean {
    if (!this.current(version)) return false
    this.appliedQuery = { ...query, offset: 0 }
    this.paging = false
    return true
  }
  page(offset: number): { version: number; query: MeetingQuery } | null {
    if (!this.appliedQuery || this.paging) return null
    this.paging = true
    return { version: ++this.version, query: { ...this.appliedQuery, offset } }
  }
  finish(version: number): void {
    if (this.current(version)) this.paging = false
  }
}
export function highlightedParts(text: string, keyword: string): { text: string; hit: boolean }[] {
  if (!keyword) return [{ text, hit: false }]
  const fold = (value: string): string => value.replace(/[A-Z]/g, (c) => c.toLowerCase())
  const source = fold(text),
    query = fold(keyword)
  const parts = []
  let cursor = 0,
    match = source.indexOf(query)
  while (match >= 0) {
    if (match > cursor) parts.push({ text: text.slice(cursor, match), hit: false })
    parts.push({ text: text.slice(match, match + query.length), hit: true })
    cursor = match + query.length
    match = source.indexOf(query, cursor)
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), hit: false })
  return parts
}
