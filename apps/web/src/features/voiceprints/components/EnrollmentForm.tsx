import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { uploadVoiceprint } from '@web/features/voiceprints/api/requests'
import type { Enrollment } from '@web/features/voiceprints/api/types'
import { useState } from 'react'

export function EnrollmentForm({
  item,
  onClose,
  onSaved,
}: {
  item: Enrollment
  onClose: () => void
  onSaved: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  return (
    <Modal
      title={`登记 ${item.name} 的声音`}
      onClose={() => {
        if (!busy) onClose()
      }}
    >
      <form
        className="voiceprint-enroll"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!file || !consent) return
          if (file.size > 20 * 1024 * 1024) {
            setError('录音不能超过 20 MiB')
            return
          }
          const form = new FormData()
          form.set('file', file)
          form.set('consent', 'true')
          form.set('expectedRevision', String(item.revision))
          setBusy(true)
          setError('')
          try {
            await uploadVoiceprint(item, { method: 'POST', body: form })
            onSaved()
          } catch (err) {
            setError(err as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        <p>选择一段清晰的单人录音，中英文均可。建议 30～120 秒，避免背景音乐和其他人的声音。</p>
        <label>
          登记录音
          <input
            type="file"
            accept="audio/wav,audio/mpeg,audio/mp4,audio/aac,audio/webm,.wav,.mp3,.m4a,.aac,.webm"
            disabled={busy}
            required
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <small className="muted">最长 3 分钟，最大 20 MiB。替换处理成功前保留原声纹。</small>
        <label className="check">
          <input
            type="checkbox"
            checked={consent}
            disabled={busy}
            onChange={(e) => setConsent(e.target.checked)}
          />
          我已取得本人知情同意，授权用于公司会议发言者识别
        </label>
        <ErrorNotice>{error}</ErrorNotice>
        <div className="form-actions">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <BusyButton className="primary" busy={busy} disabled={!file || !consent}>
            上传并提取声纹
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
