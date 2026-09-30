import type { DeliverableFile } from '@paa/api-contracts'
import { api } from '@web/api/client'

export function deliverablePath(id: string, revision: number) {
  return `/deliverables/${encodeURIComponent(id)}?revision=${revision}`
}

export async function readGeneratedFile(
  deliverableId: string,
  revision: number,
  file: DeliverableFile,
  signal: AbortSignal,
) {
  const path = `/deliverables/${encodeURIComponent(deliverableId)}/files/${encodeURIComponent(file.id)}?revision=${revision}`
  if (!Number.isSafeInteger(revision) || revision < 1 || file.url !== `/api/v1${path}`)
    throw new Error('文件地址无效，请重新打开成果。')
  const bytes = await api<ArrayBuffer>(path, { signal, cache: 'no-store' }, 'bytes')
  if (bytes.byteLength !== file.size) throw new Error('文件未完整读取，请重试。')
  return new Blob([bytes], { type: file.mimeType })
}
