import type { InputHTMLAttributes } from 'react'
import { useId } from 'react'

export function FormField({
  label,
  hint,
  error,
  id,
  'aria-describedby': describedBy,
  ...input
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string
  hint?: string
  error?: string
}) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const description = [
    describedBy,
    !error && hint && `${inputId}-hint`,
    error && `${inputId}-error`,
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div className="form-field">
      <label htmlFor={inputId}>
        {label}
        {input.required && <span aria-hidden="true"> *</span>}
      </label>
      <input
        {...input}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={description || undefined}
      />
      {error && (
        <small className="form-field-error" id={`${inputId}-error`} role="alert">
          {error}
        </small>
      )}
      {!error && hint && <small id={`${inputId}-hint`}>{hint}</small>}
    </div>
  )
}
