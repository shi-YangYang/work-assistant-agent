import type { Attachment } from '@paa/api-contracts'
import { uploadAttachment } from '@web/api/attachments'
import { epoch, isCancelled } from '@web/api/client'
import { fileKind, fileSelectionError } from '@web/utils/attachments'
import { useEffect, useRef, useState } from 'react'

export function useWorkUpload(attachments: Attachment[], change: (files: Attachment[]) => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const controller = useRef<AbortController | null>(null)
  const latest = useRef({ attachments, change })
  useEffect(() => {
    latest.current = { attachments, change }
  }, [attachments, change])
  useEffect(() => () => controller.current?.abort(), [])
  async function upload(files: File[]) {
    if (!files.length || controller.current) return []
    const selected = latest.current.attachments
    const failure =
      fileSelectionError(files) ||
      (selected.length + files.length > 9 ? '每次保存最多添加 9 个附件' : '') ||
      (selected.filter((a) => a.kind === 'audio').length +
        files.filter((f) => fileKind(f) === 'audio').length >
      3
        ? '每次最多 3 段语音'
        : '')
    if (failure) {
      setError(failure)
      return []
    }
    const request = new AbortController(),
      generation = epoch
    controller.current = request
    setBusy(true)
    setError('')
    const uploaded: Attachment[] = []
    try {
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        const attachment = await uploadAttachment({
          method: 'POST',
          body: form,
          signal: request.signal,
        })
        if (request.signal.aborted || epoch !== generation) break
        uploaded.push(attachment)
        latest.current.change([...selected, ...uploaded])
      }
    } catch (failure) {
      if (!request.signal.aborted && !isCancelled(failure)) setError(failure as Error)
    } finally {
      controller.current = null
      if (!request.signal.aborted && epoch === generation) setBusy(false)
    }
    return uploaded
  }
  return { upload, busy, error }
}
