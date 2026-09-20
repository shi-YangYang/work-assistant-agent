import type { Identity } from '@paa/api-contracts'
import { clearDesktopRequest, STORAGE } from '@web/features/auth/utils/desktop-return'
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router'

// Preserve the opaque approval request through an external DingTalk redirect.
// This never stores the desktop verifier or credentials and never auto-approves.
export function useDesktopReturn(identity: Identity | null) {
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => {
    if (location.pathname === '/desktop/connect') {
      const id = new URLSearchParams(location.search).get('request') ?? ''
      if (/^[A-Za-z0-9_-]{43}$/.test(id))
        sessionStorage.setItem(STORAGE, JSON.stringify({ id, until: Date.now() + 300000 }))
      return
    }
    if (!identity || identity.member.mustChangePassword) return
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE) ?? 'null')
      if (saved?.until > Date.now() && /^[A-Za-z0-9_-]{43}$/.test(saved.id))
        void navigate('/desktop/connect?request=' + saved.id, { replace: true })
      else clearDesktopRequest()
    } catch {
      clearDesktopRequest()
    }
  }, [identity, location.pathname, location.search, navigate])
}
