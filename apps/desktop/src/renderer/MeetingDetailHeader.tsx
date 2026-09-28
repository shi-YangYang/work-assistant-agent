import type { RefObject } from 'react'
import { ArrowLeft, Plus } from 'lucide-react'
import type { Meeting } from '../shared/contracts'
import { MeetingActions } from './MeetingActions'
import { audioTime } from './AudioPlayer'
import { recordingStateLabel } from './meeting-processing-queue'

export function MeetingDetailHeader({
  meeting,
  headingRef,
  summaryAvailable,
  onBack,
  onStart,
  canStart,
  starting,
  onChanged,
  onDeleted,
  beforeDelete,
}: {
  meeting: Meeting
  headingRef: RefObject<HTMLHeadingElement | null>
  summaryAvailable: boolean
  onBack: () => void
  onStart: () => void
  canStart: boolean
  starting: boolean
  onChanged: (meeting: Meeting) => void
  onDeleted: (id: string) => void
  beforeDelete: () => void
}): React.JSX.Element {
  return (
    <header className="meeting-detail-header">
      <div className="meeting-detail-title">
        <button
          className="text-button"
          onClick={onBack}
          aria-label="返回会议列表"
          title="返回会议列表"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 ref={headingRef} tabIndex={-1} title={meeting.title}>
          {meeting.title}
        </h1>
        <MeetingActions
          meeting={meeting}
          detail
          summaryAvailable={summaryAvailable}
          onChanged={onChanged}
          onDeleted={onDeleted}
          beforeDelete={beforeDelete}
        />
      </div>
      <div className="meeting-context">
        <span className={`meeting-state ${meeting.status}`}>
          {recordingStateLabel(meeting.status)}
        </span>
        <details className="meeting-metadata">
          <summary>
            {new Date(meeting.startedAt || meeting.createdAt).toLocaleString('zh-CN', {
              hour12: false,
            })}
            {' · '}
            {audioTime(meeting.durationMs / 1000)} · 录音信息
          </summary>
          <p>麦克风：{meeting.deviceName || '未打开设备'}</p>
        </details>
        <button className="text-button meeting-new" disabled={!canStart} onClick={onStart}>
          <Plus size={15} />
          {starting ? '正在准备…' : '开始会议'}
        </button>
      </div>
      {meeting.status === 'interrupted' && (
        <p className="audio-warning">这场会议曾中断，音频只包含可恢复的部分。</p>
      )}
      {meeting.status === 'failed' && (
        <p role="alert" className="audio-warning">
          录音未成功保存，请检查麦克风、磁盘空间与目录权限后重试。
        </p>
      )}
    </header>
  )
}
