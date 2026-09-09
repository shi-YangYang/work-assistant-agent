import { constants } from 'node:fs'
import { open, realpath } from 'node:fs/promises'
import { join, relative, isAbsolute } from 'node:path'
import { Readable } from 'node:stream'
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
export async function serveMedia(
  request: Request,
  root: string,
  core: CoreManager,
): Promise<Response> {
  let handle
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
    handle = undefined
    return new Response(Readable.toWeb(stream) as ReadableStream, {
      status: rangeHeader ? 206 : 200,
      headers,
    })
  } catch {
    return new Response(null, { status: 404 })
  } finally {
    await handle?.close()
  }
}
