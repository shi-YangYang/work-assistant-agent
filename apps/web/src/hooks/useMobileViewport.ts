import { useEffect } from 'react'

export function useMobileViewport() {
  useEffect(() => {
    const viewport = window.visualViewport
    if (!viewport) return
    const update = () => {
      const mobile = window.innerWidth <= 760 && viewport.scale === 1
      document.documentElement.style.setProperty(
        '--app-height',
        mobile ? `${viewport.height}px` : '100dvh',
      )
      document.documentElement.style.setProperty(
        '--viewport-top',
        mobile ? `${viewport.offsetTop}px` : '0px',
      )
      document.documentElement.classList.toggle(
        'keyboard-open',
        mobile && window.innerHeight - viewport.height > 120,
      )
    }
    update()
    viewport.addEventListener('resize', update)
    viewport.addEventListener('scroll', update)
    return () => {
      viewport.removeEventListener('resize', update)
      viewport.removeEventListener('scroll', update)
      document.documentElement.style.removeProperty('--app-height')
      document.documentElement.style.removeProperty('--viewport-top')
      document.documentElement.classList.remove('keyboard-open')
    }
  }, [])
}
