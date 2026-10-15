import { attachmentsReady } from '../../lib/attachment-uploads'
import controlsStyles from '../../../../styles/controls.module.css'
import styles from './MessageComposer.module.css'
import { WorkReferenceChip } from '../work-reference/WorkReferenceChip'
import { WorkReferencePicker } from '../work-reference/WorkReferencePicker'
import type { useWorkReference } from '../../hooks/composer/useWorkReference'
import { ComposerAttachmentMenu } from './ComposerAttachmentMenu'
import { MobileComposerPanel } from './MobileComposerPanel'
import {
  MobileComposerContext,
  useMobileComposerPanel,
} from '../../hooks/composer/useMobileComposerPanel'
import { ContextUsage, contextUsageLabel } from './controls/ContextUsage'
import { VoiceRecordButton, type VoiceRecording } from './controls/VoiceRecordButton'
import type { ContextUsage as Usage } from '@paa/api-contracts'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { clipboardFiles, fileAccept } from '@web/features/assistant/utils/files'
import { submitOnEnter } from '@web/features/assistant/utils/session'
import { CornerUpLeft, Plus, ArrowUp, Square, X, Keyboard } from 'lucide-react'
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
  const mobilePanel = useMobileComposerPanel({
    container: containerRef,
    textInput,
    text: composer.text,
    scope: contextKey,
    capturing,
  })
  const attachmentMenu = usePopover({
    disabled: locked || capturing || mobilePanel.mobile,
    scopeKey: contextKey,
  })
  const addImages = () => {
    attachmentMenu.close(false)
    mobilePanel.close()
    input.current?.click()
  }
  const selectFiles = () => {
    attachmentMenu.close(false)
    mobilePanel.close()
    fileInput.current?.click()
  }
  const selectWork = workReference
    ? () => {
        attachmentMenu.close(false)
        mobilePanel.close()
        workReference.setPickerOpen(true)
      }
    : undefined
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
  const showSend =
    !!composer.text.trim() ||
    !!composer.files.length ||
    interrupting ||
    busy ||
    pending ||
    !!retryWait ||
    !!task?.blocked
  const contextNotice = contextUnavailable || (contextUsage && contextUsage.state !== 'ready')
  return (
    <MobileComposerContext value={mobilePanel.value}>
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
        <div className={styles['composer']} data-dragging={dragging} data-voice={mobilePanel.voice}>
          <div className={styles['preview']}>
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
            {mobilePanel.mobile && contextNotice && (
              <small role="status" className={styles['context-notice']}>
                {contextUsageLabel(contextUsage, contextUnavailable)}
              </small>
            )}
          </div>
          <textarea
            hidden={mobilePanel.voice}
            ref={textInput}
            aria-label="工作消息"
            placeholder="询问 Noria"
            rows={1}
            maxLength={8000}
            value={composer.text}
            readOnly={busy || previewUploading || pending}
            onFocus={() => {
              if (mobilePanel.mobile) mobilePanel.close()
            }}
            onChange={(e) => change({ ...composer, text: e.target.value, key: '' })}
            onPaste={(event) => {
              const images = clipboardFiles(event.clipboardData)
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
          <div className={styles['attachment-actions']}>
            <input
              ref={input}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
              multiple
              hidden
              disabled={locked || capturing}
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
              ref={mobilePanel.mobile ? mobilePanel.trigger : attachmentMenu.triggerProps.ref}
              aria-expanded={mobilePanel.mobile ? mobilePanel.open : attachmentMenu.open}
              aria-controls={
                mobilePanel.mobile ? mobilePanel.id : attachmentMenu.triggerProps['aria-controls']
              }
              onClick={
                mobilePanel.mobile ? mobilePanel.toggle : attachmentMenu.triggerProps.onClick
              }
              className={controlsStyles['icon-button']}
              aria-label={mobilePanel.mobile ? '更多功能' : '添加附件'}
              title={mobilePanel.mobile ? '更多功能' : '添加附件'}
              aria-haspopup={mobilePanel.mobile ? undefined : 'dialog'}
              disabled={capturing || (!mobilePanel.mobile && locked)}
            >
              <Plus size={20} />
            </button>
            <ComposerAttachmentMenu
              menu={attachmentMenu}
              disabled={locked || capturing}
              addImages={addImages}
              addFiles={selectFiles}
              selectWork={selectWork}
            />
          </div>
          <MobileComposerPanel
            id={mobilePanel.id}
            mobile={mobilePanel.mobile}
            open={mobilePanel.open}
            disabled={locked || capturing}
            addImages={addImages}
            addFiles={selectFiles}
            selectWork={selectWork}
            execution={executionControl}
            reasoning={reasoningControl}
            context={
              <ContextUsage
                key={contextKey}
                usage={contextUsage}
                unavailable={contextUnavailable}
                loading={contextLoading}
              />
            }
          />
          <div className={styles['voice-action']}>
            <VoiceRecordButton
              recording={recording}
              disabled={locked}
              variant={mobilePanel.voice ? 'bar' : 'icon'}
              onActivate={
                mobilePanel.mobile && !mobilePanel.voice ? mobilePanel.switchVoice : undefined
              }
              holdDisabled={!!task?.blocked || !!retryWait || personaSaving || reasoningSaving}
              beforeStart={() => mobilePanel.close()}
            />
          </div>
          {mobilePanel.voice && (
            <button
              type="button"
              className={`${controlsStyles['icon-button']} ${styles['voice-mode-toggle']}`}
              aria-label="切换到文字输入"
              title="切换到文字输入"
              disabled={capturing}
              onClick={mobilePanel.switchText}
            >
              <Keyboard size={22} />
            </button>
          )}
          <button
            data-expanded={false}
            hidden={mobilePanel.mobile && !showSend}
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
                  (!pending && !attachmentsReady(composer.files)) ||
                  personaSaving ||
                  reasoningSaving ||
                  capturing ||
                  (!pending && task?.blocked) ||
                  (!composer.text.trim() && !composer.files.length)
            }
            onClick={() => {
              mobilePanel.close()
              void (interrupting ? task?.interrupt() : send())
            }}
          >
            {interrupting ? <Square size={15} fill="currentColor" /> : <ArrowUp size={18} />}
          </button>
        </div>
      </div>
    </MobileComposerContext>
  )
}
