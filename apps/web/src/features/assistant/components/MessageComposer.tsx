import controlsStyles from '../../../styles/controls.module.css'
import noticeStyles from '../../../components/Notice.module.css'
import styles from './MessageComposer.module.css'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import type { CaptureState, Composer } from '@web/features/assistant/lib/audio-capture'
import { clipboardImages, fileAccept } from '@web/features/assistant/utils/files'
import { submitOnEnter } from '@web/features/assistant/utils/session'
import { CornerUpLeft, ImagePlus, Mic, Send, Square, X } from 'lucide-react'
import type * as React from 'react'
import { useRef } from 'react'

export function MessageComposer({
  dragging = false,
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
  dragging?: boolean
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
  const capturing = recording.state !== 'idle'
  return (
    <div className={styles['composer-wrap']}>
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
          placeholder="今天有什么进展？也可以随时补充一条消息…"
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
            <button
              className={controlsStyles['icon-button']}
              aria-label="添加图片"
              title="添加图片"
              disabled={locked || capturing}
              onClick={() => input.current?.click()}
            >
              <ImagePlus size={20} />
            </button>
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
            <label className={styles['file-label']}>
              文件
              <input
                type="file"
                accept={fileAccept}
                multiple
                hidden
                disabled={locked || capturing}
                onChange={(e) => {
                  void addFiles(Array.from(e.target.files ?? []))
                  e.target.value = ''
                }}
              />
            </label>
          </div>
          <BusyButton
            busy={busy}
            className={`${controlsStyles['primary']} ${styles['slot-primary']}`}
            disabled={
              !!retryWait ||
              previewUploading ||
              capturing ||
              (!composer.text.trim() && !composer.files.length)
            }
            onClick={send}
          >
            <Send size={16} />
            {retryWait ? `${retryWait} 秒后再试` : pending ? '原样重试，确认结果' : '发送'}
          </BusyButton>
        </div>
      </div>
    </div>
  )
}
