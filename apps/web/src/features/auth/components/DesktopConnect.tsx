import type { Identity } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import {
  desktopAuthorizationPath,
  logout,
  resolveDesktopAuthorization,
} from '@web/features/auth/api/requests'
import { LoginBackground } from '@web/features/auth/components/LoginBackground'
import { clearDesktopRequest } from '@web/features/auth/utils/desktop-return'
import { useResource } from '@web/hooks/useResource'
import { CheckCircle2, Monitor } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation } from 'react-router'

export function DesktopConnect({
  identity,
  onLogout,
}: {
  identity: Identity
  onLogout: () => void
}) {
  const location = useLocation()
  const id = new URLSearchParams(location.search).get('request') ?? ''
  const valid = /^[A-Za-z0-9_-]{43}$/.test(id)
  const resource = useResource<{ state: string; expiresAt: string; companyName: string }>(
    desktopAuthorizationPath(valid, id),
  )
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')
  const [error, setError] = useState<Error | string>('')
  const approve = async (value: boolean) => {
    setBusy(true)
    setError('')
    try {
      await resolveDesktopAuthorization(id, { approve: value })
      clearDesktopRequest()
      setResult(value ? '已授权，请返回桌面会议助手继续。' : '已取消此次连接。')
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="login login-page">
      <LoginBackground />
      <section className="login-card desktop-connect-card">
        <span className="desktop-connect-mark">
          {result ? <CheckCircle2 size={30} /> : <Monitor size={30} />}
        </span>
        <h1>连接桌面会议助手</h1>
        {result ? (
          <>
            <p role="status">{result}</p>
            <Link to="/">返回公司工作助手</Link>
          </>
        ) : (
          <>
            {resource.data && (
              <>
                <p>
                  将以 <strong>{identity.member.name}</strong> 的身份连接{' '}
                  <strong>{resource.data.companyName}</strong>。
                </p>
                <p className="muted">
                  {identity.member.role === 'admin'
                    ? '桌面可同步公司声纹并在本机识别发言者。会议录音不会自动上传。'
                    : '当前账号可以登录桌面。公司声纹仅向管理员开放。'}
                </p>
                <p className="muted">仅当你刚刚在自己的桌面应用中发起连接时确认。</p>
              </>
            )}
            <ErrorNotice retry={resource.refresh}>
              {!valid ? '授权链接无效，请回到桌面重新连接。' : error || resource.error}
            </ErrorNotice>
            {resource.data && resource.data.state === 'pending' && (
              <div className="form-actions">
                <button disabled={busy} onClick={() => void approve(false)}>
                  取消
                </button>
                <BusyButton className="primary" busy={busy} onClick={() => void approve(true)}>
                  确认连接
                </BusyButton>
              </div>
            )}
            {resource.data?.state === 'approved' && <p>已授权，请返回桌面完成连接。</p>}
            <button
              className="text-button"
              disabled={busy}
              onClick={async () => {
                try {
                  await logout({})
                  onLogout()
                } catch (e) {
                  setError(e as Error)
                }
              }}
            >
              换一个账号登录
            </button>
          </>
        )}
      </section>
    </main>
  )
}
