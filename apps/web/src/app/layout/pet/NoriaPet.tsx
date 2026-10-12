import mark from '@paa/ui-web/mark.png'
import blink from '@paa/ui-web/pet/blink.png'
import { useSyncExternalStore } from 'react'
import { usePetImage } from './usePetImage'
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
  const markImage = usePetImage(mark, visible)
  const blinkImage = usePetImage(blink, visible && animate && !reducedMotion)
  const canAnimate = animate && !reducedMotion && !blinkImage.failed && !markImage.failed

  return (
    <span
      className={styles.pet}
      data-animate={canAnimate}
      data-paused={!visible}
      aria-hidden="true"
    >
      <span className={styles.face}>
        {markImage.failed ? (
          <span className={styles.fallback}>N</span>
        ) : (
          <>
            <img
              className={styles.mark}
              src={markImage.src}
              alt=""
              draggable={false}
              onError={markImage.onError}
            />
            {!blinkImage.failed && (
              <img
                className={styles.blink}
                src={blinkImage.src}
                alt=""
                draggable={false}
                onError={blinkImage.onError}
              />
            )}
          </>
        )}
      </span>
    </span>
  )
}
