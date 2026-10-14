import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from 'react'

type Control = 'context' | 'reasoning' | 'execution'
type PanelState = {
  mobile: boolean
  open: boolean
  scope: string
  active: Control | null
  voice: boolean
}
export const MobileComposerContext = createContext<{
  mobile: boolean
  open: boolean
  active: Control | null
  activate: (control: Control | null) => void
} | null>(null)

export function useMobileComposerControl(control: Control) {
  const panel = useContext(MobileComposerContext)
  const update = panel?.activate
  const activate = useCallback(() => update?.(control), [update, control])
  const deactivate = useCallback(() => update?.(null), [update])
  return {
    mobile: !!panel?.mobile,
    available: !panel?.mobile || (panel.open && panel.active === control),
    activate,
    deactivate,
  }
}

export function useMobileComposerPanel({
  container,
  textInput,
  text,
  scope = '',
  capturing,
}: {
  container: RefObject<HTMLDivElement | null>
  textInput: RefObject<HTMLTextAreaElement | null>
  text: string
  scope?: string
  capturing: boolean
}) {
  const [mobile, setMobile] = useState(() => window.innerWidth <= 760)
  const [state, setState] = useState<PanelState>({
    mobile,
    open: false,
    scope,
    active: null,
    voice: false,
  })
  const focusDraft = useRef(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const id = useId()
  if (state.scope !== scope || state.mobile !== mobile)
    setState({ mobile, open: false, scope, active: null, voice: false })
  else if (capturing && state.open) setState({ ...state, open: false, active: null })
  const open = state.open && state.scope === scope && mobile && !capturing
  const voice = mobile && (state.voice || capturing)
  const close = useCallback(
    (restoreFocus = false) => {
      setState((previous) => ({ ...previous, mobile, open: false, scope, active: null }))
      if (restoreFocus) trigger.current?.focus({ preventScroll: true })
    },
    [mobile, scope],
  )
  const activate = useCallback((active: Control | null) => {
    setState((previous) => ({ ...previous, active }))
  }, [])
  useEffect(() => {
    const resize = () => setMobile(window.innerWidth <= 760)
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  useLayoutEffect(() => {
    const element = textInput.current
    if (!element) return
    if (!mobile) {
      element.style.removeProperty('height')
      return
    }
    const resize = () => {
      element.style.setProperty('height', 'auto')
      element.style.setProperty('height', `${Math.max(44, Math.min(element.scrollHeight, 112))}px`)
    }
    resize()
    if (focusDraft.current && !voice) {
      focusDraft.current = false
      element.focus({ preventScroll: true })
    }
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [mobile, text, textInput, voice])
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      const target = event.target as Element
      // Control menus and permission confirmation use portals outside the composer.
      if (target.closest?.('[data-composer-layer], [role="dialog"]')) return
      if (!container.current?.contains(target)) close()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.isComposing || event.defaultPrevented || state.active)
        return
      event.preventDefault()
      close(true)
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [open, state.active, container, close])
  const toggle = () => {
    if (open) close()
    else {
      textInput.current?.blur()
      setState({ ...state, mobile, open: true, scope, active: null })
    }
  }
  const switchVoice = () => {
    textInput.current?.blur()
    setState({ mobile, open: false, scope, active: null, voice: true })
  }
  const switchText = () => {
    focusDraft.current = true
    setState({ mobile, open: false, scope, active: null, voice: false })
  }
  const value = useMemo(
    () => ({ mobile, open, active: state.active, activate }),
    [mobile, open, state.active, activate],
  )
  return { mobile, open, close, toggle, trigger, id, value, voice, switchVoice, switchText }
}
