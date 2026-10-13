import { useLayoutEffect, useRef, useState } from 'react'
import type { Location } from 'react-router'

type Menu = 'main' | 'settings'

export function useSidebarNavigation(location: Location, identityScope: string) {
  const routeMenu: Menu = location.pathname.startsWith('/settings/') ? 'settings' : 'main'
  const [selection, setSelection] = useState({
    routeKey: location.key,
    identityScope,
    menu: routeMenu,
    focus: false,
  })
  const settingsRef = useRef<HTMLButtonElement>(null)
  const backRef = useRef<HTMLButtonElement>(null)
  const current = selection.routeKey === location.key && selection.identityScope === identityScope
  const menu = current ? selection.menu : routeMenu
  if (!current) {
    setSelection({ routeKey: location.key, identityScope, menu: routeMenu, focus: false })
  }

  useLayoutEffect(() => {
    if (current && selection.focus) {
      const target = selection.menu === 'settings' ? backRef : settingsRef
      target.current?.focus()
    }
  }, [current, selection])

  const selectMenu = (next: Menu) => {
    setSelection({ routeKey: location.key, identityScope, menu: next, focus: true })
  }

  return { menu, selectMenu, settingsRef, backRef }
}
