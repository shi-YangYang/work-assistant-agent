import mark from '@paa/ui-web/mark.png'
import blink from '@paa/ui-web/pet/blink.png'
import { useState, useSyncExternalStore } from 'react'
import styles from './NoriaPet.module.css'

function subscribeVisibility(callback: () => void) {
  document.addEventListener('visibilitychange', callback)
  return () => document.removeEventListener('visibilitychange', callback)
}
const isVisible = () => !document.hidden
const reducedMotionQuery = '(prefers-reduced-motion: reduce)'
const prefersReducedMotion = () => window.matchMedia(reducedMotionQuery).matches

function subscribeReducedMotion(callback: () => void) {
  const media = window.matchMedia(reducedMotionQuery)
  media.addEventListener('change', callback)
  return () => media.removeEventListener('change', callback)
}

export function NoriaPet({ animate = false }: { animate?: boolean }) {
  const visible = useSyncExternalStore(subscribeVisibility, isVisible)
  const reducedMotion = useSyncExternalStore(subscribeReducedMotion, prefersReducedMotion)
  const [blinkFailed, setBlinkFailed] = useState(false)
  const [imageFailed, setImageFailed] = useState(false)
  const canAnimate = animate && !reducedMotion && !blinkFailed && !imageFailed

  return (
    <span
      className={styles.pet}
      data-animate={canAnimate}
      data-paused={!visible}
      aria-hidden="true"
    >
      <span className={styles.face}>
        {imageFailed ? (
          <span className={styles.fallback}>N</span>
        ) : (
          <>
            <img
              className={styles.mark}
              src={mark}
              alt=""
              draggable={false}
              onError={() => setImageFailed(true)}
            />
            {!blinkFailed && (
              <img
                className={styles.blink}
                src={blink}
                alt=""
                draggable={false}
                onError={() => setBlinkFailed(true)}
              />
            )}
          </>
        )}
      </span>
    </span>
  )
}
