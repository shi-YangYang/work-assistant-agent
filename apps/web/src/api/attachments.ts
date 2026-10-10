import type { Attachment } from '@paa/api-contracts'
import { api, write } from './client'

export function readAttachmentBytes(url: string | undefined, options: RequestInit) {
  return api<ArrayBuffer>((url ?? '').replace(/^\/api\/v1/, ''), options, 'bytes')
}

export function retryDocument(attachment: Attachment, body: Record<string, never>) {
  return write(`/uploads/${attachment.id}/retry`, body)
}

export function documentExtractionPath(
  attachmentId: string,
  start: number,
  revision: number | undefined,
  workRevision?: number,
) {
  return `/uploads/${attachmentId}/extraction?start=${start}${revision !== undefined ? `&revision=${revision}` : ''}${workRevision !== undefined ? `&workRevision=${workRevision}` : ''}`
}

export function uploadAttachment(options: RequestInit) {
  return api<Attachment>('/uploads', options)
}
