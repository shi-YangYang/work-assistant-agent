import { Mic, X } from 'lucide-react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import type { CaptureState } from '../../../lib/audio-capture'
import styles from './VoiceHoldOverlay.module.css'

const bars = [
  10, 17, 23, 30, 21, 14, 29, 43, 50, 31, 17, 25, 34, 42, 31, 24, 17, 33, 49, 39, 22, 12, 17, 15,
  11,
]

export function VoiceHoldOverlay({
  state,
  seconds,
  cancelling,
}: {
  state: CaptureState
  seconds: number
  cancelling: boolean
}) {
  const requesting = state === 'requesting'
  const status = cancelling
    ? '准备取消，松开取消，移回底部继续录音'
    : requesting
      ? '正在申请麦克风…'
      : '正在录音，松开发送，上滑取消'

  return createPortal(
    <div
      className={styles.overlay}
      data-cancelling={cancelling}
      data-recording={state === 'recording'}
    >
      <div className={styles.stage} aria-hidden="true">
        <div className={styles.feedback}>
          <div className={styles.bubble}>
            <div className={styles.wave}>
              {bars.map((height, index) => (
                <span
                  key={index}
                  style={
                    {
                      '--bar-height': `${height}px`,
                      '--bar-speed': `${550 + (index % 5) * 115}ms`,
                      '--bar-delay': `${-index * 91}ms`,
                    } as CSSProperties
                  }
                />
              ))}
            </div>
          </div>
          <div className={styles.meta}>
            <span className={styles.dot} />
            <span className={styles.time}>
              {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}
            </span>
            <span>{cancelling ? '准备取消' : requesting ? '正在申请麦克风…' : '正在录音'}</span>
          </div>
        </div>
        <div className={styles['cancel-target']}>
          <span className={styles['cancel-icon']}>
            <X size={20} />
          </span>
          <span>{cancelling ? '松开取消' : '上滑取消'}</span>
        </div>
        <div className={styles['send-arc']}>
          <strong>{cancelling ? '移回这里继续录音' : '松开发送'}</strong>
          <span className={styles.detail}>
            {cancelling ? '松开后，这段语音不会发送' : '向上滑动可取消发送'}
          </span>
          <span className={styles['finger-mark']}>
            <Mic size={18} />
          </span>
        </div>
      </div>
      <span className={styles.status} role="status">
        {status}
      </span>
    </div>,
    document.body,
  )
}
