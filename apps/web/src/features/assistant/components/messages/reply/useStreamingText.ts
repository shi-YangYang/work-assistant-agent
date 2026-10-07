import { useEffect, useMemo, useState } from 'react'

const segmenter =
  typeof Intl.Segmenter === 'function'
    ? new Intl.Segmenter(undefined, { granularity: 'grapheme' })
    : null
const motionQuery = '(prefers-reduced-motion: reduce)'

// Smooth only newly received live prefixes. A mounted/restored snapshot is
// already visible history, so it must not replay from the beginning.
export function useStreamingText(text: string, active: boolean, identity: string) {
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia?.(motionQuery).matches ?? false,
  )
  useEffect(() => {
    const query = window.matchMedia?.(motionQuery)
    if (!query) return
    const update = () => setReducedMotion(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  // Older browsers without grapheme segmentation show the snapshot directly;
  // splitting by UTF-16 units or code points would break combined emoji.
  const enabled = active && !reducedMotion && !!segmenter
  const boundaries = useMemo(
    () =>
      segmenter
        ? Array.from(segmenter.segment(text), ({ index, segment }) => index + segment.length)
        : [],
    [text],
  )
  const [display, setDisplay] = useState({
    identity,
    target: text,
    enabled,
    length: text.length,
    startLength: text.length,
  })
  let current = display
  if (display.identity !== identity || display.target !== text || display.enabled !== enabled) {
    const same = display.identity === identity
    const length =
      !enabled || (same && !text.startsWith(display.target))
        ? text.length
        : !same || display.length === 0
          ? 0
          : (boundaries.find((end) => end >= display.length) ?? text.length)
    // Reset before paint: an old generation, withdrawn prefix, or terminal
    // snapshot must never wait for an animation callback to disappear/settle.
    current = { identity, target: text, enabled, length, startLength: length }
    setDisplay(current)
  }

  const startLength = current.startLength
  useEffect(() => {
    if (!enabled || startLength >= text.length) return
    const first = boundaries.findIndex((end) => end > startLength)
    const remaining = boundaries.length - first
    // Small updates advance around 60 graphemes/s; bursts speed up to catch the
    // latest server prefix within one usual 500ms snapshot interval.
    const duration = Math.min(480, (remaining / 60) * 1000)
    const started = performance.now()
    let frame = requestAnimationFrame(advance)
    function advance(now: number) {
      const count = Math.min(remaining, Math.floor((remaining * (now - started)) / duration))
      const length = count > 0 ? boundaries[first + count - 1] : startLength
      setDisplay((previous) =>
        previous.identity === identity &&
        previous.target === text &&
        previous.enabled === enabled &&
        previous.length !== length
          ? { ...previous, length }
          : previous,
      )
      if (count < remaining) frame = requestAnimationFrame(advance)
    }
    return () => cancelAnimationFrame(frame)
  }, [boundaries, enabled, identity, startLength, text])

  return text.slice(0, current.length)
}
