import { useEffect, useRef, useState } from 'react'

export function usePetImage(source: string, visible: boolean) {
  const [src, setSrc] = useState(source)
  const [failed, setFailed] = useState(false)
  const retryId = useRef(0)

  useEffect(() => {
    if (!failed || !visible) return
    let attempts = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    let image: HTMLImageElement | undefined
    const releaseImage = () => {
      if (image) image.onload = image.onerror = null
    }
    const retry = () => {
      releaseImage()
      attempts += 1
      const url = new URL(source, document.baseURI)
      url.searchParams.set('noria-retry', String(++retryId.current))
      const nextSrc = url.href
      image = new Image()
      image.onload = () => {
        setSrc(nextSrc)
        setFailed(false)
      }
      image.onerror = () => {
        if (attempts < 2) timer = setTimeout(retry, 3000)
      }
      image.src = nextSrc
    }
    // Keep the static fallback until a replacement has actually loaded.
    timer = setTimeout(retry, 1000)
    const online = () => {
      clearTimeout(timer)
      attempts = 0
      retry()
    }
    window.addEventListener('online', online)
    return () => {
      clearTimeout(timer)
      releaseImage()
      window.removeEventListener('online', online)
    }
  }, [failed, source, visible])

  return { src, failed, onError: () => setFailed(true) }
}
