import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { ApiError } from '@web/api/client'
import styles from './NoticeToast.module.css'

export function NoticeToast({
  children,
  message,
  onDismiss,
  label,
}: {
  children: ReactNode
  message: ReactNode | Error
  onDismiss?: () => void
  label?: string
}) {
  const anchor = useRef<HTMLSpanElement>(null)
  const dismiss = useRef(onDismiss)
  const [target, setTarget] = useState<HTMLElement | null>(null)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const dismissible = !!onDismiss
  useLayoutEffect(() => {
    dismiss.current = onDismiss
  }, [onDismiss])
  useLayoutEffect(() => {
    // Native modal dialogs own the top layer and focus boundary.
    setTarget(anchor.current?.closest('dialog') ?? document.body)
  }, [])
  useEffect(() => {
    if (!dismissible || hovered || focused) return
    const delay =
      message instanceof ApiError ? Math.max(10000, message.retryAt - Date.now() + 10000) : 10000
    const timer = window.setTimeout(() => dismiss.current?.(), delay)
    return () => window.clearTimeout(timer)
  }, [message, hovered, focused, dismissible])
  return (
    <>
      <span ref={anchor} hidden />
      {target &&
        createPortal(
          <div
            className={styles.toast}
            role={label ? 'region' : undefined}
            aria-label={label}
            data-dismissible={!!onDismiss}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            onFocusCapture={() => setFocused(true)}
            onBlurCapture={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false)
            }}
          >
            {children}
            {onDismiss && (
              <button
                type="button"
                className={styles.dismiss}
                aria-label="关闭提示"
                onClick={onDismiss}
              >
                <X size={18} aria-hidden="true" />
              </button>
            )}
          </div>,
          target,
        )}
    </>
  )
}
