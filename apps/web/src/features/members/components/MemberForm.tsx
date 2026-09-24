import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import { inputRules, type Member } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { FormField } from '@web/components/FormField'
import { Modal } from '@web/components/Modal'
import { createMember, resetMemberPassword } from '@web/features/members/api/requests'
import type { ChangeEvent, SubmitEvent } from 'react'
import { useEffect, useRef, useState } from 'react'

type Field = 'name' | 'username' | 'password'
type FieldErrors = Partial<Record<Field, string>>

const constraints = inputRules.member
const usernamePattern = new RegExp(constraints.username.pattern)

export function MemberForm({
  member,
  onClose,
  onSaved,
}: {
  member: Member | null
  onClose: () => void
  onSaved: () => void
}) {
  const [values, setValues] = useState({ name: '', username: '', password: '' })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({})
  const [failure, setFailure] = useState<Error | string>('')
  const [busy, setBusy] = useState(false)
  const form = useRef<HTMLFormElement>(null)
  const submitting = useRef(false)
  const mounted = useRef(true)
  const fields: Field[] = member ? ['password'] : ['name', 'username', 'password']
  const rules = {
    name: `姓名需为 ${constraints.name.min}–${constraints.name.max} 个字符`,
    username: `账号需为 ${constraints.username.min}–${constraints.username.max} 位，仅支持字母、数字和 . _ @ -`,
    password: `密码需为 ${constraints.password.min}–${constraints.password.max} 位`,
  }
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  function validate(field: Field, value: string) {
    if (!value || (field === 'name' && !value.trim()))
      return `请输入${field === 'name' ? '姓名' : field === 'username' ? '账号' : '密码'}`
    const length = [...value].length
    if (field === 'username') return usernamePattern.test(value) ? '' : rules.username
    return length >= constraints[field].min && length <= constraints[field].max ? '' : rules[field]
  }

  function input(field: Field) {
    return {
      name: field,
      value: values[field],
      error: errors[field],
      required: true,
      readOnly: busy,
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

  function focusError(next: FieldErrors) {
    const field = fields.find((name) => next[name])
    if (field) (form.current?.elements.namedItem(field) as HTMLInputElement | null)?.focus()
  }

  function close() {
    if (!submitting.current) onClose()
  }

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current) return
    setFailure('')
    const next: FieldErrors = {}
    setTouched(Object.fromEntries(fields.map((field) => [field, true])))
    for (const field of fields) {
      next[field] = validate(field, values[field])
    }
    setErrors(next)
    if (fields.some((field) => next[field])) {
      focusError(next)
      return
    }
    submitting.current = true
    setBusy(true)
    try {
      if (member) await resetMemberPassword(member, { password: values.password })
      else await createMember({ ...values, name: values.name.trim(), role: 'employee' })
      if (mounted.current) onSaved()
    } catch (error) {
      if (!mounted.current) return
      const next: FieldErrors = {}
      if (error instanceof ApiError) {
        for (const field of fields) {
          const message = error.fieldErrors[field]
          if (message) next[field] = message
          else if (error.fields.includes(`body.${field}`)) next[field] = rules[field]
        }
        if (!member && error.status === 409 && error.code === 'username_taken')
          next.username ||= '该账号已存在，请更换账号'
      }
      if (fields.some((field) => next[field])) {
        setErrors(next)
        focusError(next)
      } else setFailure(error instanceof Error ? error : '保存失败，请稍后重试。')
    } finally {
      submitting.current = false
      if (mounted.current) setBusy(false)
    }
  }

  return (
    <Modal title={member ? `重置 ${member.name} 的密码` : '添加成员'} onClose={close}>
      <form ref={form} noValidate aria-busy={busy} onSubmit={submit}>
        {!member && (
          <>
            <FormField {...input('name')} label="姓名" autoComplete="off" />
            <FormField
              {...input('username')}
              label="账号"
              hint={`${constraints.username.min}–${constraints.username.max} 位，仅支持字母、数字和 . _ @ -`}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
            />
          </>
        )}
        <FormField
          {...input('password')}
          label="密码"
          type="password"
          autoComplete="new-password"
          hint={`${constraints.password.min}–${constraints.password.max} 位。请通过公司认可的方式交给本人。`}
        />
        <ErrorNotice>{failure}</ErrorNotice>
        <div className={layoutStyles['form-actions']}>
          <button type="button" disabled={busy} onClick={close}>
            取消
          </button>
          <BusyButton type="submit" busy={busy} className={controlsStyles['primary']}>
            保存
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
