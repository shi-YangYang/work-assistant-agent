import { useCallback, useId, useLayoutEffect, useRef, useState } from 'react'

/** Keep visibility and dismissal working even in mobile WebViews without the Popover API. */
export function usePopover({
  placement = 'top-start',
  disabled = false,
  scopeKey = '',
}: {
  placement?: 'top-start' | 'bottom-start' | 'right-end'
  disabled?: boolean
  scopeKey?: string
} = {}) {
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const [state, setState] = useState({ scopeKey, open: false })
  if (state.scopeKey !== scopeKey || (disabled && state.open)) setState({ scopeKey, open: false })
  const open = state.scopeKey === scopeKey && state.open && !disabled
  const native =
    typeof HTMLElement !== 'undefined' &&
    typeof HTMLElement.prototype.showPopover === 'function' &&
    typeof HTMLElement.prototype.hidePopover === 'function'
  const close = useCallback(
    (restoreFocus = true) => {
      setState({ scopeKey, open: false })
      if (restoreFocus) trigger.current?.focus({ preventScroll: true })
    },
    [scopeKey],
  )

  useLayoutEffect(() => {
    const element = panel.current
    const button = trigger.current
    if (!open || !element || !button) return
    if (native) element.showPopover()
    const position = () => {
      const viewport = window.visualViewport
      const left = (viewport?.offsetLeft ?? 0) + 12
      const top = (viewport?.offsetTop ?? 0) + 12
      const width = viewport?.width ?? window.innerWidth
      const height = viewport?.height ?? window.innerHeight
      element.style.maxWidth = `${Math.max(0, width - 24)}px`
      element.style.maxHeight = `${Math.max(0, height - 24)}px`
      const rect = button.getBoundingClientRect()
      const x = placement === 'right-end' ? rect.right + 10 : rect.left
      const y =
        placement === 'right-end'
          ? rect.bottom - element.offsetHeight
          : placement === 'bottom-start'
            ? rect.bottom + 8 + element.offsetHeight <= top + height - 24
              ? rect.bottom + 8
              : rect.top - element.offsetHeight - 8
            : rect.top - element.offsetHeight - 10
      element.style.left = `${Math.max(left, Math.min(x, left + width - 24 - element.offsetWidth))}px`
      element.style.top = `${Math.max(top, Math.min(y, top + height - 24 - element.offsetHeight))}px`
    }
    position()
    const resizeObserver =
      typeof ResizeObserver === 'function' ? new ResizeObserver(position) : null
    resizeObserver?.observe(element)
    const outside = (event: Event) => {
      if (!element.contains(event.target as Node) && !button.contains(event.target as Node))
        close(false)
    }
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.isComposing) return
      event.preventDefault()
      event.stopPropagation()
      close()
    }
    const toggle = () => {
      if (native && !element.matches(':popover-open')) close(false)
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('focusin', outside)
    document.addEventListener('keydown', keydown, true)
    element.addEventListener('toggle', toggle)
    window.addEventListener('resize', position)
    window.addEventListener('scroll', position, true)
    window.visualViewport?.addEventListener('resize', position)
    window.visualViewport?.addEventListener('scroll', position)
    return () => {
      resizeObserver?.disconnect()
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('focusin', outside)
      document.removeEventListener('keydown', keydown, true)
      element.removeEventListener('toggle', toggle)
      window.removeEventListener('resize', position)
      window.removeEventListener('scroll', position, true)
      window.visualViewport?.removeEventListener('resize', position)
      window.visualViewport?.removeEventListener('scroll', position)
      if (native && element.matches(':popover-open')) element.hidePopover()
    }
  }, [open, native, placement, close])

  return {
    open,
    close,
    triggerProps: {
      ref: trigger,
      'aria-expanded': open,
      'aria-controls': id,
      onClick: () => setState({ scopeKey, open: !open }),
    },
    panelProps: {
      ref: panel,
      id,
      // Use the top layer when available, but keep one dismissal path on every browser.
      popover: native ? ('manual' as const) : undefined,
      hidden: !open,
      'data-popover-open': open || undefined,
      // Explicit hiding is required: unsupported browsers have no [popover] UA stylesheet.
      style: {
        display: open ? undefined : 'none',
        zIndex: 1200,
        pointerEvents: 'auto' as const,
        bottom: 'auto',
        overflowY: 'auto' as const,
      },
    },
  }
}
