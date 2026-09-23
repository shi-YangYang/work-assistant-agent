import controlsStyles from '../styles/controls.module.css'
import styles from './Actions.module.css'
import { MoreHorizontal } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export function Actions({
  children,
  label = '更多操作',
  className = '',
}: {
  children: ReactNode
  label?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (!open || !popup.current) return
    const position = () => {
      if (!popup.current) return
      const viewport = window.visualViewport
      const bottom = viewport ? viewport.offsetTop + viewport.height : window.innerHeight
      popup.current.dataset.side = 'bottom'
      if (popup.current.getBoundingClientRect().bottom > bottom - 16)
        popup.current.dataset.side = 'top'
    }
    position()
    window.visualViewport?.addEventListener('resize', position)
    return () => window.visualViewport?.removeEventListener('resize', position)
  }, [open])
  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])
  return (
    <div
      ref={root}
      className={`${styles['action-menu']} ${className}`}
      onPointerLeave={(e) => {
        if (e.pointerType === 'mouse' && !root.current?.querySelector(':focus-visible'))
          setOpen(false)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          setOpen(false)
          trigger.current?.focus()
        }
      }}
    >
      <button
        ref={trigger}
        className={`${controlsStyles['icon-button']} ${styles['slot-icon-button']}`}
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen(!open)}
      >
        <MoreHorizontal size={19} />
      </button>
      {open && (
        <div
          ref={popup}
          className={styles['popover']}
          role="menu"
          onClick={() => {
            setOpen(false)
            trigger.current?.focus()
          }}
        >
          <div className={styles['popover-items']}>{children}</div>
        </div>
      )}
    </div>
  )
}
