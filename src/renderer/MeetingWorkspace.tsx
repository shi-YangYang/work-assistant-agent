import type { MeetingHit } from '../shared/library-contracts'
import { MeetingActions } from './MeetingActions'
import { useRef, useState, type RefObject } from 'react'
import { ArrowLeft } from 'lucide-react'
import type { Meeting } from '../shared/contracts'
import { AudioPlayer, audioTime, type AudioPlayerHandle } from './AudioPlayer'
import { MeetingMinutes } from './MeetingMinutes'
import { Transcript } from './Transcription'

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
}: {
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
      <MeetingActions
        meeting={meeting}
        detail
        summaryAvailable={summaryAvailable}
        onChanged={onChanged}
        onDeleted={onDeleted}
        beforeDelete={() => audioRef.current?.release()}
      />
      {meeting.deleting && (
        <p role="alert" className="audio-warning">
          {meeting.deletionError || '删除尚未完成，请从操作菜单重试删除。'}
        </p>
      )}
      <div className="meeting-context">
        <button className="text-button" onClick={onBack}>
          <ArrowLeft size={16} />
          返回会议列表
        </button>
        <span className={`meeting-state ${meeting.status}`}>
          {meeting.status === 'completed'
            ? '已完成'
            : meeting.status === 'interrupted'
              ? '录制中断'
              : meeting.status === 'failed'
                ? '录制失败'
                : '处理中'}
        </span>
        <details className="meeting-metadata">
          <summary>
            {new Date(meeting.startedAt || meeting.createdAt).toLocaleString('zh-CN', {
              hour12: false,
            })}{' '}
            · {audioTime(meeting.durationMs / 1000)} · 详情
          </summary>
          <p>麦克风：{meeting.deviceName || '未打开设备'}</p>
          {meeting.status === 'interrupted' && <p>这场会议曾中断，音频只包含可恢复的部分。</p>}
          {meeting.status === 'failed' && (
            <p>录音未成功保存，请检查麦克风、磁盘空间与目录权限后重试。</p>
          )}
        </details>
      </div>
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
