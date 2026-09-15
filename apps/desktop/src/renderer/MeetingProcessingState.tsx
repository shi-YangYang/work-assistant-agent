import { useEffect, useRef, useState } from 'react'
import type { MeetingState } from '../shared/contracts'
import { MeetingProcessingQueue } from './meeting-processing-queue'

const processing = new MeetingProcessingQueue({
  getTranscriptionStatus: (id) => window.paa.getTranscriptionStatus(id),
  getSummary: (id) => window.paa.getSummary(id),
})

export function MeetingProcessingState({
  meetingId,
  visible,
  connected,
  state,
  refreshVersion,
}: {
  meetingId: string
  visible: boolean
  connected: boolean
  state: MeetingState
  refreshVersion: number
}): React.JSX.Element {
  const [result, setResult] = useState({ meetingId, label: '' })
  const element = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!visible || !connected || !['completed', 'interrupted'].includes(state)) return
    const row = element.current?.closest('.meeting-row')
    if (!row) return
    let alive = true
    let unsubscribe: (() => void) | undefined
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!alive) return
        if (entry.isIntersecting) {
          unsubscribe ??= processing.subscribe(meetingId, (label) =>
            setResult({ meetingId, label }),
          )
        } else {
          unsubscribe?.()
          unsubscribe = undefined
        }
      },
      { root: row.closest('.list-page') },
    )
    observer.observe(row)
    return () => {
      alive = false
      observer.disconnect()
      unsubscribe?.()
    }
  }, [meetingId, visible, connected, state, refreshVersion])
  return (
    <small ref={element} className="processing-state">
      {result.meetingId === meetingId ? result.label : ''}
    </small>
  )
}
