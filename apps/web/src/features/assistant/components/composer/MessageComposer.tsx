import controlsStyles from '../../../../styles/controls.module.css'
import styles from './MessageComposer.module.css'
import { WorkReferenceChip } from '../work-reference/WorkReferenceChip'
import { WorkReferencePicker } from '../work-reference/WorkReferencePicker'
import type { useWorkReference } from '../../hooks/composer/useWorkReference'
import { ContextUsage } from './controls/ContextUsage'
import { VoiceRecordButton, type VoiceRecording } from './controls/VoiceRecordButton'
import type { ContextUsage as Usage } from '@paa/api-contracts'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { clipboardImages, fileAccept } from '@web/features/assistant/utils/files'
import { submitOnEnter } from '@web/features/assistant/utils/session'
import {
  CornerUpLeft,
  Plus,
  ImagePlus,
  Paperclip,
  ArrowUp,
  Square,
  X,
  BriefcaseBusiness,
} from 'lucide-react'
import type { useAssistantTask } from '../../hooks/conversation/useAssistantTask'
import type * as React from 'react'
import { useRef } from 'react'
import { usePopover } from '@web/components/overlays/usePopover'

export function MessageComposer({
  containerRef,
  dragging = false,
  empty = false,
  send,
  addFiles,
  composer,
  locked,
  change,
  textInput,
  busy,
  previewUploading,
  personaSaving = false,
  pending,
  recording,
  retryWait,
  children,
  workReference,
  executionControl,
  reasoningControl,
  reasoningSaving = false,
  questionPanel,
  contextKey,
  contextUsage = null,
  contextUnavailable = false,
  contextLoading = false,
  task,
}: {
  workReference?: ReturnType<typeof useWorkReference>
  executionControl?: React.ReactNode
  reasoningControl?: React.ReactNode
  reasoningSaving?: boolean
  questionPanel?: React.ReactNode
  task?: ReturnType<typeof useAssistantTask>
  containerRef: React.RefObject<HTMLDivElement | null>
  dragging?: boolean
  empty?: boolean
  send: () => Promise<void>
  addFiles: (files: File[]) => Promise<void>
  composer: Composer
  locked: boolean
  change: (next: Composer) => void
  textInput: React.RefObject<HTMLTextAreaElement | null>
  busy: boolean
  previewUploading: boolean
  personaSaving?: boolean
  pending: boolean
  recording: VoiceRecording
  retryWait: number
  contextKey?: string
  contextUsage?: Usage | null
  contextUnavailable?: boolean
  contextLoading?: boolean
  children: React.ReactNode
}) {
  const input = useRef<HTMLInputElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const capturing = recording.state !== 'idle'
  const attachmentMenu = usePopover({ disabled: locked || capturing, scopeKey: contextKey })
  const retryPending = pending && !busy
  const interrupting = !pending && !!task?.running
  const label = interrupting
    ? task?.cancelling
      ? '中断中'
      : '中断'
    : busy
      ? '正在发送'
      : retryWait
        ? `${retryWait} 秒后再试`
        : retryPending
          ? '原样重试，确认结果'
          : task?.blocked
            ? '正在恢复处理状态'
            : '发送'
  return (
    <div
      ref={containerRef}
      className={styles['composer-wrap']}
      data-empty={empty}
      data-question={!!questionPanel}
    >
      {questionPanel}
      {workReference?.pickerOpen && (
        <WorkReferencePicker
          selected={composer.workReference?.workId}
          onClose={() => workReference.setPickerOpen(false)}
          onSelect={workReference.select}
        />
      )}
      <div className={styles['composer']} data-dragging={dragging}>
        {composer.workReference && (
          <WorkReferenceChip
            reference={composer.workReference}
            disabled={locked}
            onRemove={workReference?.remove}
          />
        )}
        {workReference?.loading && <small role="status">正在引用工作…</small>}
        {composer.deliverableReference && (
          <div className={styles['replying']}>
            <span>继续处理：{composer.deliverableTitle ?? '当前方案'}</span>
            <button
              type="button"
              aria-label="取消成果关联"
              disabled={locked}
              onClick={() =>
                change({
                  ...composer,
                  deliverableReference: undefined,
                  deliverableTitle: undefined,
                  key: '',
                })
              }
            >
              ×
            </button>
          </div>
        )}
        {composer.replyTo && (
          <div className={styles['replying']}>
            <CornerUpLeft size={14} />
            正在补充此前消息
            <button
              className={controlsStyles['icon-button']}
              aria-label="取消补充关联"
              disabled={locked}
              onClick={() => change({ ...composer, replyTo: undefined, key: '' })}
            >
              <X size={14} />
            </button>
          </div>
        )}
        {composer.files.length > 0 && children}
        <textarea
          ref={textInput}
          aria-label="工作消息"
          placeholder="询问 Noria"
          rows={1}
          maxLength={8000}
          value={composer.text}
          readOnly={busy || previewUploading || pending}
          onChange={(e) => change({ ...composer, text: e.target.value, key: '' })}
          onPaste={(event) => {
            const images = clipboardImages(event.clipboardData)
            if (!images.length) return
            event.preventDefault()
            void addFiles(images)
          }}
          onKeyDown={(event) =>
            submitOnEnter(event, () => {
              if (pending || !task?.blocked) void send()
            })
          }
        />
        <div className={styles['composer-actions']}>
          <div>
            <input
              ref={input}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
              multiple
              hidden
              onChange={(e) => {
                void addFiles(Array.from(e.target.files ?? []))
                e.target.value = ''
              }}
            />
            <input
              ref={fileInput}
              type="file"
              accept={fileAccept}
              multiple
              hidden
              disabled={locked || capturing}
              onChange={(event) => {
                void addFiles(Array.from(event.target.files ?? []))
                event.target.value = ''
              }}
            />
            <button
              {...attachmentMenu.triggerProps}
              className={controlsStyles['icon-button']}
              aria-label="添加附件"
              title="添加附件"
              aria-haspopup="dialog"
              disabled={locked || capturing}
            >
              <Plus size={20} />
            </button>
            <div
              {...attachmentMenu.panelProps}
              className={styles['attachment-menu']}
              role="dialog"
              aria-label="添加附件"
            >
              <button
                disabled={locked || capturing}
                onClick={() => {
                  attachmentMenu.close()
                  input.current?.click()
                }}
              >
                <ImagePlus size={18} />
                <span>
                  添加图片<small>上传截图、照片或粘贴图片</small>
                </span>
              </button>
              <button
                disabled={locked || capturing}
                onClick={() => {
                  attachmentMenu.close()
                  fileInput.current?.click()
                }}
              >
                <Paperclip size={18} />
                <span>
                  添加文件<small>文档、PDF 或语音文件</small>
                </span>
              </button>
              {workReference && (
                <button
                  disabled={locked || capturing}
                  onClick={() => {
                    attachmentMenu.close()
                    workReference.setPickerOpen(true)
                  }}
                >
                  <BriefcaseBusiness size={18} />
                  <span>
                    引用工作<small>选择我的工作作为本条消息的参考</small>
                  </span>
                </button>
              )}
            </div>
            {executionControl}
          </div>
          <div className={styles['send-actions']}>
            <ContextUsage
              key={contextKey}
              usage={contextUsage}
              unavailable={contextUnavailable}
              loading={contextLoading}
            />
            {reasoningControl}
            <VoiceRecordButton
              recording={recording}
              disabled={locked}
              holdDisabled={!!task?.blocked || !!retryWait || personaSaving || reasoningSaving}
            />
            <button
              data-expanded={false}
              aria-label={label}
              aria-busy={busy || task?.cancelling}
              title={label}
              className={`${controlsStyles['primary']} ${styles['slot-primary']}`}
              disabled={
                interrupting
                  ? task?.cancelling
                  : busy ||
                    !!retryWait ||
                    previewUploading ||
                    personaSaving ||
                    reasoningSaving ||
                    capturing ||
                    (!pending && task?.blocked) ||
                    (!composer.text.trim() && !composer.files.length)
              }
              onClick={interrupting ? task?.interrupt : send}
            >
              {interrupting ? <Square size={15} fill="currentColor" /> : <ArrowUp size={18} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
