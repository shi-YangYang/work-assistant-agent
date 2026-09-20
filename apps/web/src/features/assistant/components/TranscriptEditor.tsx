import type { WorkMessage } from '@paa/api-contracts'
import { AutoTextarea } from '@web/components/AutoTextarea'
import { BusyButton } from '@web/components/BusyButton'
import { Modal } from '@web/components/Modal'
import { correctTranscript } from '@web/features/assistant/api/requests'
import type * as React from 'react'

export function TranscriptEditor({
  transcript,
  setTranscript,
  setBusy,
  message,
  onChange,
  setError,
  busy,
}: {
  transcript: boolean
  setTranscript: React.Dispatch<React.SetStateAction<boolean>>
  setBusy: React.Dispatch<React.SetStateAction<boolean>>
  message: WorkMessage
  onChange: () => void
  setError: React.Dispatch<React.SetStateAction<string | Error>>
  busy: boolean
}) {
  return (
    <>
      {transcript && (
        <Modal title="修正语音文字" onClose={() => setTranscript(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault()
              const text = new FormData(e.currentTarget).get('text')
              setBusy(true)
              try {
                await correctTranscript(message, {
                  text,
                  expectedRevision: message.transcriptRevision,
                })
                setTranscript(false)
                onChange()
              } catch (e) {
                setError(e as Error)
              } finally {
                setBusy(false)
              }
            }}
          >
            <AutoTextarea
              name="text"
              rows={3}
              defaultValue={message.transcript}
              maxLength={8000}
              required
            />
            <div className="form-actions">
              <button type="button" onClick={() => setTranscript(false)}>
                取消
              </button>
              <BusyButton busy={busy} className="primary">
                保存修正
              </BusyButton>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
