import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import styles from './MessageTranscript.module.css'
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
    <section className={styles['transcript']}>
      <div className={styles['transcript-heading']}>
        <button
          className={styles['transcript-toggle']}
          aria-expanded={transcriptOpen}
          aria-controls={`transcript-${message.id}`}
          onClick={() => setTranscriptOpen((open) => !open)}
        >
          <ChevronDown size={16} aria-hidden="true" />
          语音文字
          {!message.transcript && (
            <span className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
              待识别
            </span>
          )}
        </button>
        {own && (
          <button
            className={`${controlsStyles['text-button']} ${styles['transcript-edit']}`}
            onClick={() => setTranscript(true)}
          >
            <Pencil size={14} aria-hidden="true" />
            修正文字
          </button>
        )}
      </div>
      <div
        id={`transcript-${message.id}`}
        hidden={!transcriptOpen}
        className={styles['transcript-body']}
      >
        <p className={utilitiesStyles['preserve']}>{message.transcript || '等待识别'}</p>
      </div>
    </section>
  )
}
