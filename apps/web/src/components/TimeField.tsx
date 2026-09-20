import { Modal } from '@web/components/Modal'
import { Clock3 } from 'lucide-react'
import { useState } from 'react'

export function TimeField({
  value,
  onChange,
  required,
}: {
  value: string
  onChange: (value: string) => void
  required?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [choice, setChoice] = useState('09:00')
  const show = () => {
    setChoice(/^\d{2}:\d{2}$/.test(value) ? value : '09:00')
    setOpen(true)
  }
  return (
    <span className="time-field">
      <input
        value={value}
        required={required}
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
      <button type="button" className="icon-button" aria-label="选择时间" onClick={show}>
        <Clock3 size={17} />
      </button>
      {open && (
        <Modal title="选择时间" onClose={() => setOpen(false)}>
          <div className="time-picker">
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
          <div className="form-actions">
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
              className="primary"
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
