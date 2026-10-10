import { inputRules, type Member } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { FormField } from '@web/components/forms/FormField'
import { Modal } from '@web/components/overlays/Modal'
import { updateMember } from '@web/features/members/api/requests'
import { useRef, useState, type SubmitEvent } from 'react'
import layout from '@web/styles/layout.module.css'
import controls from '@web/styles/controls.module.css'

const rules = inputRules.member.name
const ruleMessage = `姓名需为 ${rules.min}–${rules.max} 个字符`
function validate(value: string) {
  if (!value.trim()) return '请输入姓名'
  const length = [...value].length
  return length < rules.min || length > rules.max ? ruleMessage : ''
}

export function MemberNameForm({
  member,
  onClose,
  onSaved,
}: {
  member: Member
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(member.name)
  const [error, setError] = useState('')
  const [touched, setTouched] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  const form = useRef<HTMLFormElement>(null)
  const close = () => {
    if (!submitting.current) onClose()
  }
  const focus = () => (form.current?.elements.namedItem('name') as HTMLInputElement)?.focus()
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current) return
    setTouched(true)
    setFailure('')
    const message = validate(name)
    setError(message)
    if (message) {
      focus()
      return
    }
    submitting.current = true
    setBusy(true)
    try {
      await updateMember(member, { name: name.trim() })
      onSaved()
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.fieldErrors.name || (error.fields.includes('body.name') ? ruleMessage : '')
          : ''
      if (message) {
        setError(message)
        focus()
      } else setFailure(error instanceof Error ? error : '保存失败，请稍后重试。')
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }
  return (
    <Modal title="编辑姓名" onClose={close}>
      <form ref={form} noValidate aria-busy={busy} onSubmit={submit}>
        <FormField label="账号" name="username" value={member.username} readOnly />
        <FormField
          label="姓名"
          name="name"
          value={name}
          error={error}
          required
          readOnly={busy}
          autoComplete="off"
          onChange={(event) => {
            const value = event.currentTarget.value
            setName(value)
            if (touched) setError(validate(value))
          }}
          onBlur={() => {
            setTouched(true)
            if (!error) setError(validate(name))
          }}
        />
        <ErrorNotice>{failure}</ErrorNotice>
        <div className={layout['form-actions']}>
          <button type="button" disabled={busy} onClick={close}>
            取消
          </button>
          <BusyButton type="submit" className={controls.primary} busy={busy}>
            保存
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
