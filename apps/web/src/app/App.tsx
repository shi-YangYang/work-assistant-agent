import type { Identity } from '@paa/api-contracts'
import { isCancelled, setCsrf } from '@web/api/client'
import { Shell } from '@web/app/Shell'
import { composerDraftLifecycle } from '@web/features/assistant/lib/composer-drafts'
import { readIdentity } from '@web/features/auth/api/requests'
import { DesktopConnect } from '@web/features/auth/components/DesktopConnect'
import { Login } from '@web/features/auth/components/Login'
import { useDesktopReturn } from '@web/features/auth/hooks/useDesktopReturn'
import { DingTalkAccountPage as AccountPage } from '@web/features/settings/components/AccountPage'
import { identityScope, SessionDrafts } from '@web/lib/session-drafts'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

export function App() {
  const [vault] = useState(() => new SessionDrafts(composerDraftLifecycle))
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [loading, setLoading] = useState(true)
  const location = useLocation()
  const navigate = useNavigate()
  useDesktopReturn(identity)
  const verified = useRef<string | null>(null)
  const [loadError, setLoadError] = useState<Error | string>('')
  useEffect(() => {
    const controller = new AbortController()
    void readIdentity({ signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return
        setCsrf(value.csrf)
        vault.resume(value)
        verified.current = identityScope(value)
        setIdentity(value)
      })
      .catch((e) => {
        if (!controller.signal.aborted && !isCancelled(e) && e.status !== 401) setLoadError(e)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    const expire = () => {
      vault.suspend()
      if (verified.current) setLoadError('登录已过期，请重新登录。聊天草稿仅在原账号验证后恢复。')
      setIdentity(null)
    }
    const forbidden = () => vault.clear()
    window.addEventListener('paa-session-expired', expire)
    window.addEventListener('paa-access-forbidden', forbidden)
    return () => {
      controller.abort()
      window.removeEventListener('paa-session-expired', expire)
      window.removeEventListener('paa-access-forbidden', forbidden)
    }
  }, [vault])
  const logout = () => {
    verified.current = null
    vault.clear()
    setCsrf('')
    setLoadError('')
    setIdentity(null)
    if (location.pathname !== '/desktop/connect') void navigate('/', { replace: true })
  }
  if (loading)
    return (
      <div className="login">
        <p>正在连接…</p>
      </div>
    )
  if (!identity)
    return (
      <Login
        vault={vault}
        initialError={loadError}
        onLogin={async (value) => {
          const changedAccount = verified.current && verified.current !== identityScope(value)
          setCsrf(value.csrf)
          vault.resume(value)
          if (changedAccount && location.pathname !== '/desktop/connect')
            await navigate('/', { replace: true })
          verified.current = identityScope(value)
          setLoadError('')
          setIdentity(value)
        }}
      />
    )
  if (identity.member.mustChangePassword)
    return (
      <div className="login">
        <div className="login-card">
          <h1>设置你的密码</h1>
          <p>首次登录，请更换管理员提供的临时密码。</p>
          <AccountPage force member={identity.member} onLogout={logout} />
        </div>
      </div>
    )
  if (location.pathname === '/desktop/connect')
    return <DesktopConnect identity={identity} onLogout={logout} />
  return <Shell key={identityScope(identity)} identity={identity} vault={vault} onLogout={logout} />
}
