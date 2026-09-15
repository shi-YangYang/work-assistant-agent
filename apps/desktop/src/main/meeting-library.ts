import { randomUUID } from 'node:crypto'
import { open, rename, unlink } from 'node:fs/promises'
import { basename, dirname, join } from 'node:path'
import type { CoreManager } from './core-manager'
import type { LibraryOperation, SnapshotChunk, SnapshotInfo } from '../shared/library-contracts'
import { ID_PATTERN, type Result } from '../shared/contracts'
import { mediaAccess } from './media'

type Host = {
  save(name: string, format: 'md' | 'txt'): Promise<string | null>
  copy(text: string): void | Promise<void>
}
function value<T>(result: Result<T>): T {
  if (!result.ok) throw new Error(result.message)
  return result.value
}
export async function waitOperation<T>(core: CoreManager, id: string): Promise<T> {
  for (;;) {
    const operation = value(
      await core.libraryRequest<LibraryOperation<T>>('library.status', { id }),
    )
    if (operation.state === 'failed')
      throw new Error(operation.error?.message || '资料操作失败，请重试。')
    if (operation.state === 'completed') return operation.value as T
    await new Promise((resolve) => setTimeout(resolve, 80))
  }
}
export function safeFilename(title: string, date: string, extension: string): string {
  const cleaned = title
    .replace(/[<>:"/\\|?*]/g, '_')
    .split('')
    .map((character) =>
      character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127 ? '_' : character,
    )
    .join('')
    .replace(/[. ]+$/g, '')
    .slice(0, 80)
  const safe = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(cleaned)
    ? `_${cleaned}`
    : cleaned
  return `${safe || '会议'}-${date.slice(0, 10).replace(/[^\d-]/g, '')}.${extension}`
}
export async function writeSnapshot(
  core: CoreManager,
  id: string,
  destination: string,
  bytes: number,
): Promise<void> {
  const staging = join(dirname(destination), `.${basename(destination)}.${randomUUID()}.tmp`)
  const file = await open(staging, 'wx', 0o600)
  try {
    let offset = 0
    while (offset < bytes) {
      const chunk = value(await core.libraryRequest<SnapshotChunk>('library.read', { id, offset }))
      const data = Buffer.from(chunk.data, 'base64')
      if (
        !data.length ||
        data.length > 16384 ||
        chunk.nextOffset !== offset + data.length ||
        chunk.nextOffset > bytes ||
        chunk.done !== (chunk.nextOffset === bytes)
      )
        throw new Error('快照内容不完整，请重新导出。')
      let written = 0
      while (written < data.length)
        written += (await file.write(data, written, data.length - written)).bytesWritten
      offset = chunk.nextOffset
    }
    await file.sync()
    await file.close()
    await rename(staging, destination)
  } finally {
    await file.close()
    await unlink(staging).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error
    })
  }
}
export class DesktopLibrary {
  private exporting = false
  constructor(
    private core: CoreManager,
    private host: Host,
  ) {}
  async execute(action: unknown, input: unknown): Promise<Result<unknown>> {
    let operation: string | undefined
    let unblock: (() => void) | undefined
    let ownsExport = false
    try {
      if (
        !input ||
        typeof input !== 'object' ||
        Array.isArray(input) ||
        JSON.stringify(input).length > 4096
      )
        throw new Error('请求参数无效。')
      const params = input as Record<string, unknown>
      if (
        action !== 'search' &&
        (typeof params.meetingId !== 'string' || !ID_PATTERN.test(params.meetingId))
      )
        throw new Error('会议标识无效。')
      const expected =
        action === 'search'
          ? 'from,offset,text,to'
          : action === 'rename'
            ? 'meetingId,title'
            : action === 'export'
              ? 'format,meetingId,scope,timestamps'
              : 'meetingId'
      if (Object.keys(params).sort().join() !== expected) throw new Error('请求参数无效。')
      if (action === 'rename') return this.core.libraryRequest('meetings.rename', params)
      if (!['search', 'delete', 'copy', 'export'].includes(String(action)))
        throw new Error('请求参数无效。')
      if (action === 'delete') unblock = await mediaAccess.block(params.meetingId as string)
      if (action === 'export' || action === 'copy') {
        if (this.exporting) throw new Error('已有复制或导出操作，请完成后再试。')
        this.exporting = ownsExport = true
      }
      const exporting = action === 'export' || action === 'copy'
      const options =
        action === 'copy'
          ? { ...params, format: 'txt', scope: 'summary', timestamps: false }
          : params
      operation = value(
        await this.core.libraryRequest<{ id: string }>('library.start', {
          kind: exporting ? 'export' : action,
          input: options,
        }),
      ).id
      const result = await waitOperation<unknown>(this.core, operation)
      if (!exporting) return { ok: true, value: result }
      const info = result as SnapshotInfo
      if (
        !Number.isSafeInteger(info.bytes) ||
        info.bytes < 0 ||
        info.bytes > 1_000_000_000 ||
        typeof info.title !== 'string' ||
        typeof info.date !== 'string'
      )
        throw new Error('导出快照无效。')
      if (action === 'copy') {
        if (info.bytes > 1_000_000) throw new Error('纪要过长，无法复制，请使用导出。')
        const chunks: Buffer[] = []
        let offset = 0
        while (offset < info.bytes) {
          const chunk = value(
            await this.core.libraryRequest<SnapshotChunk>('library.read', {
              id: operation,
              offset,
            }),
          )
          const buffer = Buffer.from(chunk.data, 'base64')
          if (
            !buffer.length ||
            chunk.nextOffset !== offset + buffer.length ||
            chunk.nextOffset > info.bytes
          )
            throw new Error('快照内容不完整，请重试。')
          chunks.push(buffer)
          offset = chunk.nextOffset
        }
        await this.host.copy(Buffer.concat(chunks).toString('utf8'))
        return { ok: true, value: { copied: true } }
      }
      const format = options.format as 'md' | 'txt'
      const destination = await this.host.save(safeFilename(info.title, info.date, format), format)
      if (!destination) return { ok: true, value: { canceled: true } }
      await writeSnapshot(this.core, operation, destination, info.bytes)
      return { ok: true, value: { canceled: false } }
    } catch (error) {
      return {
        ok: false,
        message: error instanceof Error ? error.message : '资料操作失败，请重试。',
      }
    } finally {
      if (operation)
        await this.core.libraryRequest('library.release', { id: operation }).catch(() => {})
      unblock?.()
      if (ownsExport) this.exporting = false
    }
  }
}
