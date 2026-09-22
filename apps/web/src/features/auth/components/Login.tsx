import type { Identity } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { login } from '@web/features/auth/api/requests'
import { DingTalkLogin } from '@web/features/auth/components/DingTalkLogin'
import { DingTalkResult } from '@web/features/auth/components/DingTalkResult'
import { LoginBook } from '@web/features/auth/components/LoginBook'
import { dingtalkResult } from '@web/features/auth/utils/dingtalk-flow'
import { SessionDrafts } from '@web/lib/session-drafts'
import { useRef, useState } from 'react'
import { useLocation } from 'react-router'

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
  const [dingtalkBusy, setDingtalkBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const location = useLocation()
  const [initiallyOpen] = useState(() => Boolean(initialError || dingtalkResult(location.search)))
  const signingIn = busy || dingtalkBusy
  return (
    <LoginBook
      initiallyOpen={initiallyOpen}
      busy={signingIn}
      onClose={() => {
        formRef.current?.reset()
        setError('')
        setShowPassword(false)
      }}
    >
      <section className="book-form" aria-labelledby="login-title">
        <header className="book-form__header">
          <p className="book-form__eyebrow">WELCOME BACK</p>
          <h1 id="login-title">登录工作助手</h1>
          <p className="book-form__caption">你的工作，从这里继续。</p>
        </header>
        <DingTalkResult />
        <form
          className="book-form__form"
          ref={formRef}
          aria-busy={busy}
          onSubmit={async (e) => {
            e.preventDefault()
            if (signingIn) return
            const data = new FormData(e.currentTarget)
            setBusy(true)
            setError('')
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
          <label className="book-form__field">
            <span>账号</span>
            <input
              name="username"
              placeholder="输入账号"
              autoComplete="username"
              required
              maxLength={80}
            />
          </label>
          <div className="book-form__field book-form__password">
            <label htmlFor="login-password">密码</label>
            <input
              id="login-password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              placeholder="输入密码"
              autoComplete="current-password"
              required
              maxLength={128}
            />
            <button
              type="button"
              className="book-form__visibility"
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? '隐藏' : '显示'}
            </button>
          </div>
          <ErrorNotice>{error}</ErrorNotice>
          <BusyButton busy={busy} disabled={dingtalkBusy} className="book-form__submit">
            <span>登录</span>
            <span aria-hidden="true">↗</span>
          </BusyButton>
        </form>
        <DingTalkLogin vault={vault} disabled={busy} onBusyChange={setDingtalkBusy} />
        <small className="book-form__help">尚无账号？请联系公司管理员</small>
      </section>
    </LoginBook>
  )
}
