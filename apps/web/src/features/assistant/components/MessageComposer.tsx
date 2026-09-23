import controlsStyles from '../../../styles/controls.module.css'
import noticeStyles from '../../../components/Notice.module.css'
import styles from './MessageComposer.module.css'
import { ErrorNotice } from '@web/components/ErrorNotice'
import type { CaptureState, Composer } from '@web/features/assistant/lib/audio-capture'
import { clipboardImages, fileAccept } from '@web/features/assistant/utils/files'
import { submitOnEnter } from '@web/features/assistant/utils/session'
import {
  CornerUpLeft,
  Plus,
  ImagePlus,
  Mic,
  Paperclip,
  ArrowUp,
  LoaderCircle,
  Square,
  X,
} from 'lucide-react'
import type * as React from 'react'
import { useId, useRef } from 'react'

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
  pending,
  sendError,
  recording,
  retryWait,
  children,
}: {
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
  pending: boolean
  sendError: string | Error
  recording: { state: CaptureState; seconds: number; start: () => Promise<void>; stop: () => void }
  retryWait: number
  children: React.ReactNode
}) {
  const input = useRef<HTMLInputElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const attachmentTrigger = useRef<HTMLButtonElement>(null)
  const attachmentMenu = useRef<HTMLDivElement>(null)
  const attachmentMenuId = useId()
  const capturing = recording.state !== 'idle'
  return (
    <div ref={containerRef} className={styles['composer-wrap']} data-empty={empty}>
      <div className={styles['composer']} data-dragging={dragging}>
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
          placeholder="发消息，或告诉我你想推进的工作…"
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
          onKeyDown={(event) => submitOnEnter(event, () => void send())}
        />
        {pending && !busy && (
          <p className={noticeStyles['notice']} role="status">
            原消息的提交结果尚未确认。请原样重试以确认结果，不会重复创建消息；确认前暂不修改内容。
          </p>
        )}
        <ErrorNotice>{sendError}</ErrorNotice>
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
              ref={attachmentTrigger}
              className={controlsStyles['icon-button']}
              aria-label="添加附件"
              title="添加附件"
              aria-haspopup="dialog"
              popoverTarget={attachmentMenuId}
              disabled={locked || capturing}
            >
              <Plus size={20} />
            </button>
            <div
              ref={attachmentMenu}
              id={attachmentMenuId}
              className={styles['attachment-menu']}
              popover="auto"
              role="dialog"
              aria-label="添加附件"
              onToggle={(event) => {
                if (event.newState !== 'open') return
                const rect = attachmentTrigger.current?.getBoundingClientRect()
                const menu = event.currentTarget
                if (rect) {
                  menu.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - menu.offsetWidth - 12))}px`
                  menu.style.top = `${Math.max(12, rect.top - menu.offsetHeight - 10)}px`
                }
              }}
            >
              <button
                disabled={locked || capturing}
                onClick={() => {
                  attachmentMenu.current?.hidePopover()
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
                  attachmentMenu.current?.hidePopover()
                  fileInput.current?.click()
                }}
              >
                <Paperclip size={18} />
                <span>
                  添加文件<small>文档、PDF 或语音文件</small>
                </span>
              </button>
            </div>
            {capturing ? (
              <button
                className={styles['recording']}
                disabled={recording.state === 'stopping'}
                onClick={() => recording.stop()}
              >
                <Square size={15} />
                {recording.state === 'requesting'
                  ? '取消麦克风申请'
                  : recording.state === 'stopping'
                    ? '正在结束录音…'
                    : `停止 · ${recording.seconds} 秒`}
              </button>
            ) : (
              <button
                className={controlsStyles['icon-button']}
                title="录制语音"
                aria-label="录制语音"
                disabled={locked}
                onClick={recording.start}
              >
                <Mic size={20} />
              </button>
            )}
          </div>
          <button
            aria-label={
              busy
                ? '正在发送'
                : retryWait
                  ? `${retryWait} 秒后再试`
                  : pending
                    ? '原样重试，确认结果'
                    : '发送'
            }
            aria-busy={busy}
            title={busy ? '正在发送' : '发送'}
            data-expanded={!!retryWait || pending}
            className={`${controlsStyles['primary']} ${styles['slot-primary']}`}
            disabled={
              busy ||
              !!retryWait ||
              previewUploading ||
              capturing ||
              (!composer.text.trim() && !composer.files.length)
            }
            onClick={send}
          >
            {busy ? <LoaderCircle size={18} /> : <ArrowUp size={18} />}
            {retryWait || pending ? (
              <span>{retryWait ? `${retryWait} 秒后再试` : '原样重试，确认结果'}</span>
            ) : null}
          </button>
        </div>
      </div>
    </div>
  )
}
