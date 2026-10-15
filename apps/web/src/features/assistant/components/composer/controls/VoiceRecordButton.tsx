import { Mic, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import type { CaptureState } from '../../../lib/audio-capture'
import controls from '@web/styles/controls.module.css'
import { VoiceHoldOverlay } from './VoiceHoldOverlay'
import styles from './VoiceRecordButton.module.css'

export type VoiceRecording = {
  state: CaptureState
  seconds: number
  start: (directSend?: boolean) => Promise<boolean | void>
  stop: (send?: boolean) => void
  cancel: () => void
}
type Press = {
  id: number
  y: number
  x: number
  held: boolean
  cancel: boolean
  timer: ReturnType<typeof setTimeout>
}

export function VoiceRecordButton({
  recording,
  disabled,
  holdDisabled = false,
  beforeStart,
  variant = 'icon',
  onActivate,
}: {
  recording: VoiceRecording
  disabled: boolean
  holdDisabled?: boolean
  beforeStart?: () => void
  variant?: 'icon' | 'bar'
  onActivate?: () => void
}) {
  const [holding, setHolding] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const press = useRef<Press | null>(null)
  const suppressClick = useRef(false)
  const button = useRef<HTMLButtonElement>(null)
  const capturing = recording.state !== 'idle'
  const label = capturing
    ? recording.state === 'requesting'
      ? '取消麦克风申请'
      : recording.state === 'stopping'
        ? '正在结束录音'
        : `停止录音 · ${recording.seconds} 秒`
    : onActivate
      ? '切换到语音输入'
      : variant === 'bar'
        ? '点击录音，长按发送'
        : '录制语音'

  function clearPress() {
    const current = press.current
    press.current = null
    if (current) {
      clearTimeout(current.timer)
      if (button.current?.hasPointerCapture?.(current.id))
        button.current.releasePointerCapture(current.id)
    }
    setHolding(false)
    setCancelling(false)
    return current
  }
  function abort() {
    const current = clearPress()
    if (current) suppressClick.current = true
    if (current?.held) {
      button.current?.blur()
      recording.cancel()
    }
  }
  useEffect(() => {
    const hidden = () => {
      if (document.hidden) abort()
    }
    const blur = () => abort()
    window.addEventListener('blur', blur)
    document.addEventListener('visibilitychange', hidden)
    return () => {
      window.removeEventListener('blur', blur)
      document.removeEventListener('visibilitychange', hidden)
    }
  })
  useEffect(
    () => () => {
      if (press.current) clearTimeout(press.current.timer)
      press.current = null
    },
    [],
  )
  function down(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || event.isPrimary === false || press.current) return
    suppressClick.current = false
    if (capturing || disabled || holdDisabled || onActivate) return
    event.currentTarget.setPointerCapture?.(event.pointerId)
    const current: Press = {
      id: event.pointerId,
      y: event.clientY,
      x: event.clientX,
      held: false,
      cancel: false,
      timer: setTimeout(() => {
        if (press.current !== current) return
        current.held = true
        suppressClick.current = true
        setHolding(true)
        beforeStart?.()
        void recording.start(true).then((started) => {
          if (started === false && press.current === current) clearPress()
        })
      }, 350),
    }
    press.current = current
  }
  function move(event: PointerEvent<HTMLButtonElement>) {
    const current = press.current
    if (!current || current.id !== event.pointerId) return
    if (!current.held) {
      if (Math.hypot(event.clientY - current.y, event.clientX - current.x) > 12) abort()
      return
    }
    // Keep a return threshold so small finger movements at the boundary do not flicker.
    current.cancel = current.y - event.clientY >= (current.cancel ? 40 : 60)
    setCancelling(current.cancel)
  }
  function up(event: PointerEvent<HTMLButtonElement>) {
    if (press.current?.id !== event.pointerId) return
    const current = clearPress()
    if (!current?.held) return
    if (current.cancel) {
      event.currentTarget.blur()
      recording.cancel()
    } else recording.stop(true)
  }

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`${variant === 'bar' ? styles.bar : controls['icon-button']} ${styles.button}`}
        data-recording={capturing}
        data-holding={holding}
        data-cancelling={holding && cancelling}
        aria-label={label}
        title={capturing || onActivate ? label : '点击录音，长按说话、松开发送，上滑取消'}
        disabled={capturing ? recording.state === 'stopping' : disabled}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={abort}
        onLostPointerCapture={abort}
        onContextMenu={(event) => event.preventDefault()}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && press.current) abort()
        }}
        onClick={(event) => {
          if (suppressClick.current && event.detail !== 0) {
            suppressClick.current = false
            return
          }
          suppressClick.current = false
          if (capturing) recording.stop()
          else if (onActivate) onActivate()
          else {
            beforeStart?.()
            void recording.start()
          }
        }}
      >
        {variant === 'bar' ? (
          holding ? (
            cancelling ? (
              '松开取消'
            ) : (
              '松开发送，上滑取消'
            )
          ) : capturing ? (
            label
          ) : (
            '点击录音，长按发送'
          )
        ) : capturing ? (
          <>
            <Square size={14} fill="currentColor" />
            <span className={styles.time} aria-hidden="true">
              {recording.seconds}s
            </span>
          </>
        ) : (
          <Mic size={20} />
        )}
      </button>
      {holding && (
        <VoiceHoldOverlay
          state={recording.state}
          seconds={recording.seconds}
          cancelling={cancelling}
        />
      )}
    </>
  )
}
