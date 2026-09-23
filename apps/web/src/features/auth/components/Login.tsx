import formFieldStyles from '../../../components/FormField.module.css'
import loginStyles from '../styles/login-form.module.css'
import { inputRules, type Identity } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { login } from '@web/features/auth/api/requests'
import { DingTalkLogin } from '@web/features/auth/components/DingTalkLogin'
import { DingTalkResult } from '@web/features/auth/components/DingTalkResult'
import { LoginBook } from '@web/features/auth/components/LoginBook'
import { dingtalkResult } from '@web/features/auth/utils/dingtalk-flow'
import { SessionDrafts } from '@web/lib/session-drafts'
import type { ChangeEvent, SubmitEvent } from 'react'
import { useRef, useState } from 'react'
import { useLocation } from 'react-router'

type Field = 'username' | 'password'
type FieldErrors = Partial<Record<Field, string>>
const fields: Field[] = ['username', 'password']
const labels = { username: '账号', password: '密码' }
const rules = {
  username: `账号需为 1–${inputRules.member.username.max} 位`,
  password: `密码需为 1–${inputRules.member.password.max} 位`,
}

function validate(field: Field, value: string) {
  if (!value) return `请输入${labels[field]}`
  return [...value].length <= inputRules.member[field].max ? '' : rules[field]
}

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
  const [values, setValues] = useState({ username: '', password: '' })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({})
  const formRef = useRef<HTMLFormElement>(null)
  const submitting = useRef(false)
  const location = useLocation()
  const [initiallyOpen] = useState(() => Boolean(initialError || dingtalkResult(location.search)))
  const signingIn = busy || dingtalkBusy

  function input(field: Field) {
    return {
      name: field,
      id: `login-${field}`,
      value: values[field],
      required: true,
      readOnly: signingIn,
      'aria-invalid': errors[field] ? (true as const) : undefined,
      'aria-describedby': errors[field] ? `login-${field}-error` : undefined,
      onChange: (event: ChangeEvent<HTMLInputElement>) => {
        const value = event.currentTarget.value
        setValues((current) => ({ ...current, [field]: value }))
        if (touched[field])
          setErrors((current) => ({ ...current, [field]: validate(field, value) }))
      },
      onBlur: () => {
        setTouched((current) => ({ ...current, [field]: true }))
        setErrors((current) =>
          current[field] ? current : { ...current, [field]: validate(field, values[field]) },
        )
      },
    }
  }

  function fieldError(field: Field) {
    return errors[field] ? (
      <small
        className={`${formFieldStyles['form-field-error']} ${loginStyles['login-field-error']}`}
        id={`login-${field}-error`}
        role="alert"
      >
        {errors[field]}
      </small>
    ) : null
  }

  function focusError(next: FieldErrors) {
    const field = fields.find((name) => next[name])
    if (field) (formRef.current?.elements.namedItem(field) as HTMLInputElement | null)?.focus()
  }

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    if (signingIn || submitting.current) return
    setError('')
    setTouched({ username: true, password: true })
    const next = Object.fromEntries(fields.map((field) => [field, validate(field, values[field])]))
    setErrors(next)
    if (fields.some((field) => next[field])) {
      focusError(next)
      return
    }
    submitting.current = true
    setBusy(true)
    try {
      await onLogin(await login(values))
    } catch (error) {
      const next: FieldErrors = {}
      if (error instanceof ApiError) {
        for (const field of fields) {
          if (error.fieldErrors[field]) next[field] = error.fieldErrors[field]
          else if (error.fields.includes(`body.${field}`)) next[field] = rules[field]
        }
      }
      if (fields.some((field) => next[field])) {
        setErrors(next)
        focusError(next)
      } else setError(error instanceof Error ? error : '登录失败，请稍后重试。')
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  return (
    <LoginBook
      initiallyOpen={initiallyOpen}
      busy={signingIn}
      onClose={() => {
        setValues({ username: '', password: '' })
        setErrors({})
        setTouched({})
        setError('')
        setShowPassword(false)
      }}
    >
      <section className={loginStyles['book-form']} aria-labelledby="login-title">
        <header className={loginStyles['book-form__header']}>
          <p className={loginStyles['book-form__eyebrow']}>WELCOME BACK</p>
          <h1 id="login-title">登录工作助手</h1>
          <p className={loginStyles['book-form__caption']}>你的工作，从这里继续。</p>
        </header>
        <DingTalkResult className={loginStyles['login-notice']} />
        <form
          className={loginStyles['book-form__form']}
          ref={formRef}
          noValidate
          aria-busy={busy}
          onSubmit={submit}
        >
          <div className={loginStyles['book-form__field']}>
            <label htmlFor="login-username">账号</label>
            <input
              {...input('username')}
              placeholder="输入账号"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
            />
            {fieldError('username')}
          </div>
          <div
            className={`${loginStyles['book-form__field']} ${loginStyles['book-form__password']}`}
          >
            <label htmlFor="login-password">密码</label>
            <input
              {...input('password')}
              type={showPassword ? 'text' : 'password'}
              placeholder="输入密码"
              autoComplete="current-password"
            />
            <button
              type="button"
              className={loginStyles['book-form__visibility']}
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? '隐藏' : '显示'}
            </button>
            {fieldError('password')}
          </div>
          <ErrorNotice
            className={loginStyles['login-notice']}
            actionsClassName={loginStyles['login-notice-actions']}
          >
            {error}
          </ErrorNotice>
          <BusyButton
            busy={busy}
            disabled={dingtalkBusy}
            className={loginStyles['book-form__submit']}
          >
            <span>登录</span>
            <span aria-hidden="true">↗</span>
          </BusyButton>
        </form>
        <DingTalkLogin vault={vault} disabled={busy} onBusyChange={setDingtalkBusy} />
        <small className={loginStyles['book-form__help']}>尚无账号？请联系公司管理员</small>
      </section>
    </LoginBook>
  )
}
