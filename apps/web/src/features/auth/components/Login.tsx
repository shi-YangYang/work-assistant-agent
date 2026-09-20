import type { Identity } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { login } from '@web/features/auth/api/requests'
import { DingTalkLogin } from '@web/features/auth/components/DingTalkLogin'
import { DingTalkResult } from '@web/features/auth/components/DingTalkResult'
import { LoginBackground } from '@web/features/auth/components/LoginBackground'
import { SessionDrafts } from '@web/lib/session-drafts'
import { useState } from 'react'

export function Login({
  vault,
  onLogin,
  initialError,
}: {
  vault: SessionDrafts
  onLogin: (value: Identity) => void | Promise<void>
  initialError: Error | string
}) {
  const [error, setError] = useState(initialError)
  const [busy, setBusy] = useState(false)
  return (
    <main className="login login-page">
      <LoginBackground />
      <section className="login-panel" aria-labelledby="login-title">
        <header className="login-heading">
          <span className="brand-mark" aria-hidden="true" />
          <h1 id="login-title">登录工作助手</h1>
        </header>
        <DingTalkResult />
        <DingTalkLogin vault={vault} />
        <form
          className="login-form"
          onSubmit={async (e) => {
            e.preventDefault()
            const data = new FormData(e.currentTarget)
            setBusy(true)
            try {
              await onLogin(
                await login({
                  username: data.get('username'),
                  password: data.get('password'),
                }),
              )
            } catch (e) {
              setError(e as Error)
            } finally {
              setBusy(false)
            }
          }}
        >
          <label>
            账号
            <input
              name="username"
              placeholder="输入账号"
              autoComplete="username"
              required
              maxLength={80}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              placeholder="输入密码"
              autoComplete="current-password"
              required
              maxLength={128}
            />
          </label>
          <ErrorNotice>{error}</ErrorNotice>
          <BusyButton busy={busy} className="primary">
            登录
          </BusyButton>
        </form>
        <small className="login-help">尚无账号？请联系公司管理员</small>
      </section>
    </main>
  )
}
