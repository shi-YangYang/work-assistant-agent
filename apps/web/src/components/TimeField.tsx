import controlsStyles from '../styles/controls.module.css'
import layoutStyles from '../styles/layout.module.css'
import formFieldStyles from './FormField.module.css'
import styles from './TimeField.module.css'
import { Modal } from '@web/components/Modal'
import { Clock3 } from 'lucide-react'
import { useId, useState } from 'react'

export function TimeField({
  value,
  onChange,
  required,
  error,
}: {
  value: string
  onChange: (value: string) => void
  required?: boolean
  error?: string
}) {
  const errorId = useId()
  const [open, setOpen] = useState(false)
  const [choice, setChoice] = useState('09:00')
  const show = () => {
    setChoice(/^\d{2}:\d{2}$/.test(value) ? value : '09:00')
    setOpen(true)
  }
  return (
    <span className={formFieldStyles['form-field']} style={{ margin: 0 }}>
      <span className={styles['time-field']}>
        <input
          value={value}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          placeholder="时:分"
          inputMode="numeric"
          pattern="([01][0-9]|2[0-3]):[0-5][0-9]"
          onChange={(e) => onChange(e.target.value)}
          onClick={show}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              show()
            }
          }}
        />
        <button
          type="button"
          className={`${controlsStyles['icon-button']} ${styles['slot-icon-button']}`}
          aria-label="选择时间"
          onClick={show}
        >
          <Clock3 size={17} />
        </button>
      </span>
      {error && (
        <small className={formFieldStyles['form-field-error']} id={errorId} role="alert">
          {error}
        </small>
      )}
      {open && (
        <Modal title="选择时间" onClose={() => setOpen(false)}>
          <div className={styles['time-picker']}>
            <label>
              时
              <select
                value={choice.slice(0, 2)}
                onChange={(e) => setChoice(e.target.value + choice.slice(2))}
              >
                {Array.from({ length: 24 }, (_, n) => String(n).padStart(2, '0')).map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
            <span>:</span>
            <label>
              分
              <select
                value={choice.slice(3)}
                onChange={(e) => setChoice(choice.slice(0, 3) + e.target.value)}
              >
                {Array.from({ length: 60 }, (_, n) => String(n).padStart(2, '0')).map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
          </div>
          <div className={layoutStyles['form-actions']}>
            <button
              type="button"
              onClick={() => {
                onChange('')
                setOpen(false)
              }}
            >
              清空
            </button>
            <button
              type="button"
              className={controlsStyles['primary']}
              onClick={() => {
                onChange(choice)
                setOpen(false)
              }}
            >
              确定
            </button>
          </div>
        </Modal>
      )}
    </span>
  )
}
