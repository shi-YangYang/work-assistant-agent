import utilitiesStyles from '../../../../../styles/utilities.module.css'
import styles from './MessageTranscript.module.css'
import type { WorkMessage } from '@paa/api-contracts'
import { ChevronDown } from 'lucide-react'

export function MessageTranscriptControls({
  transcriptOpen,
  message,
  onToggle,
  own,
  onEdit,
}: {
  transcriptOpen: boolean
  message: WorkMessage
  onToggle: () => void
  own: boolean
  onEdit: () => void
}) {
  return (
    <div className={styles['transcript-controls']}>
      <button
        type="button"
        className={styles['transcript-toggle']}
        aria-expanded={transcriptOpen}
        aria-controls={`transcript-${message.id}`}
        title={message.transcript ? '查看本条消息的语音转写' : '等待识别'}
        onClick={onToggle}
      >
        转文字
        <ChevronDown size={12} aria-hidden="true" />
        {!message.transcript && <span className="sr-only">待识别</span>}
      </button>
      {own && (
        <button type="button" onClick={onEdit}>
          改文字
        </button>
      )}
    </div>
  )
}

export function MessageTranscript({
  message,
  transcriptOpen,
}: {
  message: WorkMessage
  transcriptOpen: boolean
}) {
  return (
    <div
      id={`transcript-${message.id}`}
      hidden={!transcriptOpen}
      className={styles['transcript-body']}
    >
      <p className={utilitiesStyles['preserve']}>{message.transcript || '等待识别'}</p>
    </div>
  )
}
