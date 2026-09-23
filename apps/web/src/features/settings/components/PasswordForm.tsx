import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import { inputRules, type DingTalkAccount } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { FormField } from '@web/components/FormField'
import type { useDingTalkRedirect } from '@web/features/auth/hooks/useDingTalkRedirect'
import { changePassword } from '@web/features/settings/api/requests'
import type { ChangeEvent, SubmitEvent } from 'react'
import { useEffect, useRef, useState } from 'react'

type Field = 'currentPassword' | 'newPassword' | 'confirmPassword'
type FieldErrors = Partial<Record<Field, string>>
const limits = inputRules.member.password
const labels = { currentPassword: '当前密码', newPassword: '新密码', confirmPassword: '确认新密码' }
const rules = {
  currentPassword: `当前密码不能超过 ${limits.max} 位`,
  newPassword: `新密码需为 ${limits.min}–${limits.max} 位`,
  confirmPassword: '两次新密码不一致',
}

export function PasswordForm({
  account,
  hasPassword,
  redirect,
  onSaved,
  onFailure,
}: {
  account: DingTalkAccount | null | undefined
  hasPassword: boolean
  redirect: Pick<ReturnType<typeof useDingTalkRedirect>, 'busy' | 'launch'>
  onSaved: () => void
  onFailure: () => void
}) {
  const [values, setValues] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({})
  const [failure, setFailure] = useState<Error | string>('')
  const [busy, setBusy] = useState(false)
  const [useDingTalk, setUseDingTalk] = useState(false)
  const form = useRef<HTMLFormElement>(null)
  const submitting = useRef(false)
  const mounted = useRef(true)
  const verified = !!account?.passwordVerified
  const viaDingTalk = !hasPassword || useDingTalk || verified
  const blocked = viaDingTalk && !verified
  const fields: Field[] = viaDingTalk
    ? ['newPassword', 'confirmPassword']
    : ['currentPassword', 'newPassword', 'confirmPassword']
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  function validate(field: Field, value: string, newPassword = values.newPassword) {
    if (!value) return `请输入${labels[field]}`
    if (field === 'confirmPassword') return value === newPassword ? '' : rules.confirmPassword
    const length = [...value].length
    const min = field === 'newPassword' ? limits.min : 1
    return length >= min && length <= limits.max ? '' : rules[field]
  }

  function input(field: Field) {
    return {
      name: field,
      type: 'password',
      value: values[field],
      error: field === 'currentPassword' && viaDingTalk ? undefined : errors[field],
      label: labels[field],
      required: field !== 'currentPassword' || !viaDingTalk,
      readOnly: busy,
      disabled: field === 'currentPassword' ? viaDingTalk : blocked,
      autoComplete: field === 'currentPassword' ? 'current-password' : 'new-password',
      onChange: (event: ChangeEvent<HTMLInputElement>) => {
        const value = event.currentTarget.value
        setValues((current) => ({ ...current, [field]: value }))
        setErrors((current) => ({
          ...current,
          ...(touched[field] && { [field]: validate(field, value) }),
          ...(field === 'newPassword' &&
            touched.confirmPassword && {
              confirmPassword: validate('confirmPassword', values.confirmPassword, value),
            }),
        }))
      },
      onBlur: () => {
        setTouched((current) => ({ ...current, [field]: true }))
        setErrors((current) =>
          current[field] ? current : { ...current, [field]: validate(field, values[field]) },
        )
      },
    }
  }

  function focusError(next: FieldErrors) {
    const field = fields.find((name) => next[name])
    if (field) (form.current?.elements.namedItem(field) as HTMLInputElement | null)?.focus()
  }

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current || blocked) return
    setFailure('')
    setTouched(Object.fromEntries(fields.map((field) => [field, true])))
    const next: FieldErrors = Object.fromEntries(
      fields.map((field) => [field, validate(field, values[field])]),
    )
    setErrors(next)
    if (fields.some((field) => next[field])) {
      focusError(next)
      return
    }
    submitting.current = true
    setBusy(true)
    try {
      await changePassword({
        currentPassword: viaDingTalk ? '' : values.currentPassword,
        newPassword: values.newPassword,
        useDingTalk: viaDingTalk,
      })
      if (mounted.current) onSaved()
    } catch (error) {
      if (!mounted.current) return
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
      } else setFailure(error instanceof Error ? error : '保存失败，请稍后重试。')
      onFailure()
    } finally {
      submitting.current = false
      if (mounted.current) setBusy(false)
    }
  }

  return (
    <form ref={form} noValidate aria-busy={busy} onSubmit={submit}>
      {hasPassword && !verified && <FormField {...input('currentPassword')} />}
      {account?.bound && account.available && (
        <>
          {hasPassword && !verified && (
            <label className={layoutStyles['check']}>
              <input
                type="checkbox"
                checked={useDingTalk}
                disabled={busy}
                onChange={(event) => setUseDingTalk(event.target.checked)}
              />
              忘记密码，使用钉钉重新验证
            </label>
          )}
          {viaDingTalk && (
            <p>
              {verified
                ? '已验证本人钉钉身份，请在 5 分钟内设置新密码。'
                : '请先重新验证已绑定的本人钉钉身份，再输入新密码。'}
            </p>
          )}
          {viaDingTalk && !verified && (
            <BusyButton
              type="button"
              busy={redirect.busy}
              onClick={() => redirect.launch('reauthenticate')}
            >
              重新验证钉钉身份
            </BusyButton>
          )}
        </>
      )}
      {!hasPassword && !account?.available && (
        <p>钉钉登录当前不可用，请联系管理员恢复入口后验证身份，或由管理员重置密码。</p>
      )}
      <FormField {...input('newPassword')} hint={`${limits.min}–${limits.max} 位`} />
      <FormField {...input('confirmPassword')} />
      <small>保存后所有已登录设备均需重新登录。</small>
      <ErrorNotice>{failure}</ErrorNotice>
      <div className={layoutStyles['form-actions']}>
        <BusyButton
          type="submit"
          busy={busy}
          className={controlsStyles['primary']}
          disabled={blocked}
        >
          保存密码并重新登录
        </BusyButton>
      </div>
    </form>
  )
}
