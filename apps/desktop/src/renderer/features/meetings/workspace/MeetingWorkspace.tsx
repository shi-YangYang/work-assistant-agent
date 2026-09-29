import type { MeetingHit } from '../../../../shared/library-contracts'
import { MeetingDetailHeader } from './MeetingDetailHeader'
import { useRef, useState, type RefObject } from 'react'
import type { Meeting } from '../../../../shared/contracts'
import { AudioPlayer, type AudioPlayerHandle } from '../playback/AudioPlayer'
import { MeetingMinutes } from '../minutes/MeetingMinutes'
import { Transcript } from '../transcript/Transcription'

export function MeetingWorkspace({
  meeting,
  hit,
  onChanged,
  onDeleted,
  audioRef,
  connected,
  playable,
  modelReady,
  onBack,
  onServices,
  onModels,
  headingRef,
  onStart,
  canStart,
  starting,
}: {
  headingRef: RefObject<HTMLHeadingElement | null>
  onStart: () => void
  canStart: boolean
  starting: boolean
  meeting: Meeting
  hit?: MeetingHit | null
  onChanged: (meeting: Meeting) => void
  onDeleted: (id: string) => void
  audioRef: RefObject<AudioPlayerHandle | null>
  connected: boolean
  playable: boolean
  modelReady: boolean
  onBack: () => void
  onServices: () => void
  onModels: () => void
}): React.JSX.Element {
  const [tab, setTab] = useState<'minutes' | 'transcript'>(
    hit?.source === 'transcript' ? 'transcript' : 'minutes',
  )
  const [target, setTarget] = useState<{ id: string; request: number } | null>(
    hit?.source === 'transcript' ? { id: hit.segmentId, request: 0 } : null,
  )
  const [summaryAvailable, setSummaryAvailable] = useState(false)
  const tabs = useRef<HTMLDivElement>(null)
  function change(next: typeof tab): void {
    setTab(next)
    requestAnimationFrame(() =>
      tabs.current?.querySelector<HTMLButtonElement>(`[data-tab="${next}"]`)?.focus(),
    )
  }
  const seek = (ms: number): void => {
    if (playable) audioRef.current?.seek(ms)
  }
  return (
    <section className="meeting-detail" aria-label="会议工作区">
      <MeetingDetailHeader
        meeting={meeting}
        headingRef={headingRef}
        summaryAvailable={summaryAvailable}
        onBack={onBack}
        onStart={onStart}
        canStart={canStart}
        starting={starting}
        onChanged={onChanged}
        onDeleted={onDeleted}
        beforeDelete={() => audioRef.current?.release()}
      />
      {meeting.deleting && (
        <p role="alert" className="audio-warning">
          {meeting.deletionError || '删除尚未完成，请从操作菜单重试删除。'}
        </p>
      )}
      {!meeting.deleting && (
        <>
          <div
            ref={tabs}
            className="tabs"
            role="tablist"
            aria-label="会议内容"
            onKeyDown={(event) => {
              if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
                event.preventDefault()
                change(
                  event.key === 'Home'
                    ? 'minutes'
                    : event.key === 'End'
                      ? 'transcript'
                      : tab === 'minutes'
                        ? 'transcript'
                        : 'minutes',
                )
              }
            }}
          >
            <button
              id="minutes-tab"
              data-tab="minutes"
              role="tab"
              aria-selected={tab === 'minutes'}
              aria-controls="minutes-panel"
              tabIndex={tab === 'minutes' ? 0 : -1}
              onClick={() => change('minutes')}
            >
              纪要
            </button>
            <button
              id="transcript-tab"
              data-tab="transcript"
              role="tab"
              aria-selected={tab === 'transcript'}
              aria-controls="transcript-panel"
              tabIndex={tab === 'transcript' ? 0 : -1}
              onClick={() => change('transcript')}
            >
              文字记录
            </button>
          </div>
          <div className="meeting-panels">
            <div
              id="minutes-panel"
              role="tabpanel"
              aria-labelledby="minutes-tab"
              hidden={tab !== 'minutes'}
              className="meeting-panel"
            >
              <MeetingMinutes
                meetingId={meeting.id}
                hit={hit?.source === 'summary' ? hit : null}
                onSummaryAvailable={setSummaryAvailable}
                playable={playable && meeting.audioAvailable}
                connected={connected}
                visible={tab === 'minutes'}
                onSeek={seek}
                onServices={onServices}
                onTranscript={(id) => {
                  if (id) setTarget({ id, request: Date.now() })
                  if (id) setTab('transcript')
                  else change('transcript')
                }}
              />
            </div>
            <div
              id="transcript-panel"
              role="tabpanel"
              aria-labelledby="transcript-tab"
              hidden={tab !== 'transcript'}
              className="meeting-panel"
            >
              <Transcript
                onModels={onModels}
                meetingId={meeting.id}
                modelReady={modelReady}
                playable={playable && meeting.audioAvailable}
                visible={tab === 'transcript'}
                connected={connected}
                target={target}
                onSeek={seek}
              />
            </div>
          </div>
        </>
      )}
      {meeting.audioError ? (
        <p role="alert" className="audio-warning">
          {meeting.audioError}
        </p>
      ) : meeting.audioAvailable ? (
        <AudioPlayer
          ref={audioRef}
          meetingId={meeting.id}
          durationMs={meeting.durationMs}
          enabled={playable}
        />
      ) : (
        <p className="player-unavailable">当前没有可播放的录音。</p>
      )}
    </section>
  )
}
