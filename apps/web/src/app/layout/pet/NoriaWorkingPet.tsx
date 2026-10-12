import working from '@paa/ui-web/pet/working.png'
import { useEffect, useRef, useState } from 'react'
import { usePetImage } from './usePetImage'
import { createTypingRenderer } from './typing-animation'
import styles from './NoriaPet.module.css'

export function NoriaWorkingPet({
  active,
  animate,
  visible,
}: {
  active: boolean
  animate: boolean
  visible: boolean
}) {
  const source = usePetImage(working, visible)
  const [loaded, setLoaded] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drawRef = useRef<((time: number) => void) | null>(null)
  const timeRef = useRef(0)
  const { src, onError } = source
  const errorRef = useRef(onError)
  useEffect(() => {
    errorRef.current = onError
  }, [onError])
  useEffect(() => {
    const image = new Image()
    let disposed = false
    image.onload = () => {
      if (disposed || !canvasRef.current) return
      try {
        const draw = createTypingRenderer(image, canvasRef.current)
        if (!draw) {
          errorRef.current()
          return
        }
        draw(0)
        drawRef.current = draw
        setLoaded(true)
      } catch {
        errorRef.current()
      }
    }
    image.onerror = () => {
      if (!disposed) errorRef.current()
    }
    image.src = src
    return () => {
      disposed = true
      image.onload = image.onerror = null
      drawRef.current = null
    }
  }, [src])
  useEffect(() => {
    if (!loaded || source.failed) return
    if (!active || !animate || !visible) {
      drawRef.current?.(0)
      return
    }
    let raf = 0,
      previous = 0,
      rendered = 0
    const tick = (now: number) => {
      if (previous) timeRef.current += Math.min(now - previous, 50)
      previous = now
      if (now - rendered >= 1000 / 30) {
        drawRef.current?.(timeRef.current)
        rendered = now
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [active, animate, visible, loaded, source.failed])
  return (
    <canvas
      ref={canvasRef}
      className={styles.working}
      width={204}
      height={204}
      data-ready={loaded && !source.failed}
      data-active={active}
      data-typing={active && animate && visible && loaded && !source.failed}
      aria-hidden="true"
    />
  )
}
