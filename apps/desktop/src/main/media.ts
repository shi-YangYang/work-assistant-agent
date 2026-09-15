import { constants } from 'node:fs'
import { open, realpath } from 'node:fs/promises'
import { join, relative, isAbsolute } from 'node:path'
import { Readable } from 'node:stream'
import type { ReadStream } from 'node:fs'
import { ACTIVE_STATES, ID_PATTERN } from '../shared/contracts'
import type { CoreManager } from './core-manager'

export function byteRange(
  range: string | null,
  size: number,
): { start: number; end: number } | null {
  if (!range) return { start: 0, end: size - 1 }
  const match = /^bytes=(\d*)-(\d*)$/.exec(range)
  if (!match || (!match[1] && !match[2])) return null
  const start = match[1] ? Number(match[1]) : Math.max(0, size - Number(match[2]))
  const end = match[1] && match[2] ? Math.min(Number(match[2]), size - 1) : size - 1
  return Number.isSafeInteger(start) &&
    Number.isSafeInteger(end) &&
    start >= 0 &&
    start <= end &&
    start < size
    ? { start, end }
    : null
}
export class MediaAccess {
  private blocked = new Set<string>()
  private requests = new Map<string, Set<Promise<void>>>()
  private streams = new Map<string, Set<ReadStream>>()
  begin(id: string): (() => void) | null {
    if (this.blocked.has(id)) return null
    let finish!: () => void
    const pending = new Promise<void>((resolve) => {
      finish = resolve
    })
    const requests = this.requests.get(id) ?? new Set()
    this.requests.set(id, requests)
    requests.add(pending)
    return () => {
      requests.delete(pending)
      if (!requests.size) this.requests.delete(id)
      finish()
    }
  }
  track(id: string, stream: ReadStream): void {
    const streams = this.streams.get(id) ?? new Set()
    this.streams.set(id, streams)
    streams.add(stream)
    stream.once('close', () => {
      streams.delete(stream)
      if (!streams.size) this.streams.delete(id)
    })
  }
  async block(id: string): Promise<() => void> {
    if (this.blocked.has(id)) throw new Error('这场会议正在删除，请稍后重试。')
    this.blocked.add(id)
    await Promise.all(this.requests.get(id) ?? [])
    await Promise.all(
      [...(this.streams.get(id) ?? [])].map(
        (stream) =>
          new Promise<void>((resolve) => {
            if (stream.closed) resolve()
            else {
              stream.once('close', resolve)
              stream.destroy()
            }
          }),
      ),
    )
    return () => {
      this.blocked.delete(id)
    }
  }
}
export const mediaAccess = new MediaAccess()
export async function serveMedia(
  request: Request,
  root: string,
  core: CoreManager,
  access = mediaAccess,
): Promise<Response> {
  let handle
  let finish: (() => void) | null = null
  try {
    const url = new URL(request.url)
    const id = url.pathname.slice(1)
    if (
      url.protocol !== 'paa-audio:' ||
      url.hostname !== 'meeting' ||
      url.search ||
      url.hash ||
      url.username ||
      url.password ||
      !ID_PATTERN.test(id) ||
      !['GET', 'HEAD'].includes(request.method)
    )
      return new Response(null, { status: 403 })
    finish = access.begin(id)
    if (!finish) return new Response(null, { status: 409 })
    const recording = await core.recordingStatus()
    if (!recording.ok || ACTIVE_STATES.includes(recording.value.state))
      return new Response(null, { status: 409 })
    const meeting = await core.internalMeeting(id)
    if (!meeting.audioAvailable || !meeting.audioPath) return new Response(null, { status: 404 })
    if (!new RegExp(`^meetings/${id}/(?:audio|recovered)\\.wav$`).test(meeting.audioPath))
      return new Response(null, { status: 403 })
    const actualRoot = await realpath(root)
    const candidate = join(actualRoot, meeting.audioPath)
    const actual = await realpath(candidate)
    const rel = relative(actualRoot, actual)
    if (rel.startsWith('..') || isAbsolute(rel) || actual !== candidate)
      return new Response(null, { status: 403 })
    handle = await open(actual, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
    const stat = await handle.stat()
    if (!stat.isFile() || stat.size !== 44 + meeting.bytes)
      return new Response(null, { status: 404 })
    const rangeHeader = request.headers.get('range')
    const range = byteRange(rangeHeader, stat.size)
    if (!range)
      return new Response(null, {
        status: 416,
        headers: { 'Content-Range': `bytes */${stat.size}` },
      })
    const headers: Record<string, string> = {
      'Content-Type': 'audio/wav',
      'Accept-Ranges': 'bytes',
      'Content-Length': String(range.end - range.start + 1),
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    }
    if (rangeHeader) headers['Content-Range'] = `bytes ${range.start}-${range.end}/${stat.size}`
    if (request.method === 'HEAD')
      return new Response(null, { status: rangeHeader ? 206 : 200, headers })
    const stream = handle.createReadStream({ start: range.start, end: range.end, autoClose: true })
    access.track(id, stream)
    handle = undefined
    return new Response(Readable.toWeb(stream) as ReadableStream, {
      status: rangeHeader ? 206 : 200,
      headers,
    })
  } catch {
    return new Response(null, { status: 404 })
  } finally {
    try {
      await handle?.close()
    } finally {
      finish?.()
    }
  }
}
