import type { WorkMessage } from '@paa/api-contracts'
import { ChevronDown, Pencil } from 'lucide-react'
import type * as React from 'react'

export function MessageTranscript({
  transcriptOpen,
  message,
  setTranscriptOpen,
  own,
  setTranscript,
}: {
  transcriptOpen: boolean
  message: WorkMessage
  setTranscriptOpen: React.Dispatch<React.SetStateAction<boolean>>
  own: boolean
  setTranscript: React.Dispatch<React.SetStateAction<boolean>>
}) {
  return (
    <section className="transcript">
      <div className="transcript-heading">
        <button
          className="transcript-toggle"
          aria-expanded={transcriptOpen}
          aria-controls={`transcript-${message.id}`}
          onClick={() => setTranscriptOpen((open) => !open)}
        >
          <ChevronDown size={16} aria-hidden="true" />
          语音文字
          {!message.transcript && <span className="muted small-text">待识别</span>}
        </button>
        {own && (
          <button className="text-button transcript-edit" onClick={() => setTranscript(true)}>
            <Pencil size={14} aria-hidden="true" />
            修正文字
          </button>
        )}
      </div>
      <div id={`transcript-${message.id}`} hidden={!transcriptOpen} className="transcript-body">
        <p className="preserve">{message.transcript || '等待识别'}</p>
      </div>
    </section>
  )
}
