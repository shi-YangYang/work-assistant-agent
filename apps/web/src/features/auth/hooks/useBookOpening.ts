import { useEffect, useRef, useState } from 'react'

type BookPhase = 'closed' | 'opening' | 'open' | 'closing'

// Keep the focus hand-off in sync with the cover's CSS transition.
const TURN_DURATION = 1650

export function useBookOpening(initiallyOpen: boolean, busy: boolean, onClose: () => void) {
  const [phase, setPhase] = useState<BookPhase>(initiallyOpen ? 'open' : 'closed')
  const [instant, setInstant] = useState(initiallyOpen)
  const hostRef = useRef<HTMLDivElement>(null)
  const openRef = useRef<HTMLButtonElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef(false)

  useEffect(() => {
    if (phase !== 'opening' && phase !== 'closing') return
    const timer = window.setTimeout(
      () => setPhase(phase === 'opening' ? 'open' : 'closed'),
      TURN_DURATION,
    )
    return () => window.clearTimeout(timer)
  }, [phase])

  useEffect(() => {
    if (phase === 'open') {
      // Avoid opening the software keyboard before a phone user chooses a field.
      const target = window.matchMedia('(hover: hover) and (pointer: fine)').matches
        ? hostRef.current?.querySelector<HTMLInputElement>('input[name="username"]')
        : closeRef.current
      target?.focus({ preventScroll: true })
    } else if (phase === 'closed' && returnFocus.current) {
      openRef.current?.focus({ preventScroll: true })
      returnFocus.current = false
    }
  }, [phase])

  function open(skip = false) {
    if (phase !== 'closed') return
    const quick = skip || window.matchMedia('(prefers-reduced-motion: reduce)').matches
    setInstant(quick)
    setPhase(quick ? 'open' : 'opening')
  }

  function close() {
    if (phase !== 'open' || busy) return
    const quick = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    // Move focus out before making the form inert.
    closeRef.current?.blur()
    if (hostRef.current?.contains(document.activeElement))
      (document.activeElement as HTMLElement).blur()
    returnFocus.current = true
    onClose()
    setInstant(quick)
    setPhase(quick ? 'closed' : 'closing')
  }

  return { phase, instant, hostRef, openRef, closeRef, open, close }
}
