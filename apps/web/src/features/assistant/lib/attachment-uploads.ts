import type { Attachment } from '@paa/api-contracts'
import { uploadAttachment, deleteDraftAttachment } from '@web/api/attachments'
import { ApiError, epoch, isCancelled } from '@web/api/client'
import type { DraftStore } from '@web/lib/workspace'
import type { Composer, PendingFile } from './audio-capture'

type Writer = (key: string, value: unknown) => void
type Upload = {
  file: PendingFile
  draft: string
  controller?: AbortController
  attachment?: Attachment
  protected: boolean
  removed: boolean
}
type Transport = {
  upload: (file: File, signal: AbortSignal) => Promise<Attachment>
  remove: (id: string) => Promise<unknown>
}

export function attachmentsReady(files: PendingFile[]) {
  return files.every((file) => !!file.attachment && !file.failed)
}

export class AttachmentUploads {
  private entries = new Map<string, Upload>()
  private writer?: Writer
  private scope = ''
  private active = 0
  private generation = 0
  private pumping = false
  constructor(private transport: Transport) {}

  bind(scope: string, writer: Writer) {
    if (this.writer === writer && this.scope === scope) return
    this.pause()
    this.scope = scope
    this.writer = writer
  }
  pause() {
    this.generation++
    this.writer = undefined
    for (const entry of this.entries.values()) entry.controller?.abort()
    this.entries.clear()
  }
  sync(drafts: DraftStore) {
    if (!this.writer) return
    const seen = new Set<string>()
    for (const [draft, value] of Object.entries(drafts)) {
      if (!draft.startsWith('composer:') || !value) continue
      const composer = value as Composer
      for (const file of composer.files) {
        if (file.directSend) continue
        seen.add(file.id)
        let entry = this.entries.get(file.id)
        if (!entry) {
          entry = { file, draft, attachment: file.attachment, protected: false, removed: false }
          this.entries.set(file.id, entry)
        } else {
          entry.file = file
          entry.draft = draft
        }
        if (composer.sending || composer.pending) entry.protected = true
        else entry.protected = false
      }
    }
    for (const [id, entry] of this.entries) {
      if (seen.has(id)) continue
      entry.removed = true
      entry.controller?.abort()
      if (entry.attachment && !entry.protected) this.cleanup(entry.attachment.id)
      this.entries.delete(id)
    }
    this.pump()
  }
  retry(id: string) {
    const entry = this.entries.get(id)
    if (!entry || entry.controller || entry.attachment || !entry.file.failed) return
    entry.file = { ...entry.file, failed: false, uploadState: 'queued', uploadError: undefined }
    this.publish(entry, entry.file)
    this.pump()
  }
  private publish(entry: Upload, update: Partial<PendingFile>) {
    this.writer?.(entry.draft, (previous: Composer | undefined) => {
      if (!previous?.files.some((file) => file.id === entry.file.id)) return previous
      return {
        ...previous,
        files: previous.files.map((file) =>
          file.id === entry.file.id ? { ...file, ...update } : file,
        ),
      }
    })
  }
  private cleanup(id: string) {
    // Cleanup is best effort; server tombstones and 24-hour expiry retain recovery.
    void this.transport.remove(id).catch(() => {})
  }
  private pump() {
    if (!this.writer || this.pumping) return
    this.pumping = true
    for (const entry of this.entries.values()) {
      if (this.active >= 2) break
      if (
        entry.controller ||
        entry.attachment ||
        entry.file.failed ||
        entry.removed ||
        entry.protected
      )
        continue
      const generation = this.generation
      const requestEpoch = epoch
      entry.controller = new AbortController()
      this.active++
      this.publish(entry, { uploadState: 'uploading', uploadError: undefined })
      void this.transport
        .upload(entry.file.file, entry.controller.signal)
        .then((attachment) => {
          if (entry.removed || generation !== this.generation) {
            if (requestEpoch === epoch && !entry.protected) this.cleanup(attachment.id)
            return
          }
          entry.attachment = attachment
          this.publish(entry, {
            attachment,
            uploadState: 'ready',
            failed: false,
            uploadError: undefined,
          })
        })
        .catch((error: unknown) => {
          if (entry.removed || generation !== this.generation) return
          const message =
            error instanceof ApiError &&
            ['validation', 'forbidden', 'rate_limited'].includes(error.category)
              ? error.message
              : '文件上传失败，请重试或移除。'
          entry.file = { ...entry.file, failed: true }
          this.publish(entry, {
            failed: true,
            uploadState: 'failed',
            uploadError: isCancelled(error) ? '上传已中断，请重试。' : message,
          })
        })
        .finally(() => {
          this.active--
          entry.controller = undefined
          this.pump()
        })
    }
    this.pumping = false
  }
}

export const attachmentUploads = new AttachmentUploads({
  upload(file, signal) {
    const body = new FormData()
    body.append('file', file)
    return uploadAttachment({ method: 'POST', body, signal })
  },
  remove: deleteDraftAttachment,
})
