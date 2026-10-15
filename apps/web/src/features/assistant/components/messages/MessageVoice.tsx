import type { WorkMessage } from '@paa/api-contracts'
import { AudioPlayer } from '@web/components/media/AudioPlayer'
import { useState } from 'react'
import { MessageTranscript, MessageTranscriptControls } from './transcript/MessageTranscript'
import { TranscriptEditor } from './transcript/TranscriptEditor'
import styles from './MessageVoice.module.css'

export function MessageVoice({
  message,
  own,
  onChange,
}: {
  message: WorkMessage
  own: boolean
  onChange: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const audio = message.attachments.filter((attachment) => attachment.kind === 'audio')
  const multiple = audio.length > 1
  if (!audio.length && !message.transcript) return null
  const controls = (
    <MessageTranscriptControls
      message={message}
      own={own}
      transcriptOpen={expanded}
      onToggle={() => setExpanded((open) => !open)}
      onEdit={() => setEditing(true)}
    />
  )
  const transcript = <MessageTranscript message={message} transcriptOpen={expanded} />
  return (
    <section className={styles.group} aria-label="语音消息">
      <div className={styles.strip} data-multiple={multiple} data-expanded={expanded}>
        {audio.map((attachment, index) => (
          <div className={styles.row} key={attachment.id}>
            <AudioPlayer
              src={attachment.previewUrl ?? attachment.url}
              name={attachment.name}
              duration={attachment.duration}
              label={multiple ? `语音 ${index + 1}` : undefined}
              suspended={editing}
            />
            {!multiple && controls}
          </div>
        ))}
        {(multiple || !audio.length) && <div className={styles.footer}>{controls}</div>}
        {transcript}
      </div>
      {own && (
        <TranscriptEditor
          transcript={editing}
          setTranscript={setEditing}
          busy={busy}
          setBusy={setBusy}
          message={message}
          onChange={onChange}
        />
      )}
    </section>
  )
}
