import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

const drawerQuery = '(max-width: 1023px)'

export function useNavigationDrawer(routeKey: string) {
  const [navigation, setNavigation] = useState({ routeKey, expanded: false })
  const sidebarRef = useRef<HTMLElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const expandedNav = navigation.routeKey === routeKey && navigation.expanded
  if (navigation.routeKey !== routeKey) setNavigation({ routeKey, expanded: false })
  const setExpandedNav = useCallback(
    (expanded: boolean) =>
      setNavigation({ routeKey, expanded: expanded && window.matchMedia(drawerQuery).matches }),
    [routeKey],
  )

  useEffect(() => {
    const media = window.matchMedia(drawerQuery)
    const close = () => setExpandedNav(false)
    media.addEventListener('change', close)
    return () => media.removeEventListener('change', close)
  }, [setExpandedNav])

  useLayoutEffect(() => {
    if (!expandedNav) return
    const sidebar = sidebarRef.current
    const main = mainRef.current
    const trigger = triggerRef.current
    if (!sidebar || !main) return
    const focusable = () =>
      Array.from(sidebar.querySelectorAll<HTMLElement>('a[href], button, [tabindex]')).filter(
        (element) =>
          element.tabIndex >= 0 &&
          !element.matches(':disabled') &&
          element.getClientRects().length > 0,
      )
    const modalOpen = () => document.querySelector('dialog[open]') !== null
    const wasInert = main.inert
    main.inert = true
    focusable()[0]?.focus()
    const keydown = (event: KeyboardEvent) => {
      // A command dialog owns focus while open; the native settings popover closes first.
      if (event.defaultPrevented || event.isComposing || modalOpen()) return
      if (event.key === 'Escape') {
        if (sidebar.querySelector(':popover-open')) return
        event.preventDefault()
        setExpandedNav(false)
      } else if (event.key === 'Tab') {
        const elements = focusable()
        const index = elements.indexOf(document.activeElement as HTMLElement)
        const next = event.shiftKey
          ? (index <= 0 ? elements.length : index) - 1
          : (index + 1) % elements.length
        event.preventDefault()
        elements[next]?.focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('keydown', keydown)
      sidebar.querySelector<HTMLElement>(':popover-open')?.hidePopover()
      main.inert = wasInert
      if (!modalOpen()) {
        if (trigger?.getClientRects().length) trigger.focus()
        else focusable()[0]?.focus()
      }
    }
  }, [expandedNav, setExpandedNav])

  return { expandedNav, setExpandedNav, sidebarRef, mainRef, triggerRef }
}
