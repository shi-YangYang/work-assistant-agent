import type { WorkMessage } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { AutoTextarea } from '@web/components/AutoTextarea'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { correctTranscript } from '@web/features/assistant/api/requests'
import type * as React from 'react'
import { useState } from 'react'

export function TranscriptEditor({
  transcript,
  setTranscript,
  setBusy,
  message,
  onChange,
  busy,
}: {
  transcript: boolean
  setTranscript: React.Dispatch<React.SetStateAction<boolean>>
  setBusy: React.Dispatch<React.SetStateAction<boolean>>
  message: WorkMessage
  onChange: () => void
  busy: boolean
}) {
  const [error, setError] = useState<Error | string>('')
  const fieldError = error instanceof ApiError ? error.fieldErrors.text : ''
  const close = () => {
    setError('')
    setTranscript(false)
  }
  return (
    <>
      {transcript && (
        <Modal title="修正语音文字" onClose={close}>
          <form
            onSubmit={async (e) => {
              e.preventDefault()
              const text = String(new FormData(e.currentTarget).get('text') ?? '')
              setError('')
              setBusy(true)
              try {
                await correctTranscript(message, {
                  text,
                  expectedRevision: message.transcriptRevision,
                })
                close()
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
              aria-label="语音文字"
              aria-invalid={fieldError ? true : undefined}
              onChange={() => setError('')}
            />
            <ErrorNotice>{fieldError || error}</ErrorNotice>
            <div className="form-actions">
              <button type="button" onClick={close}>
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
