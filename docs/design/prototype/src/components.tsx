import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import * as Icons from 'lucide-react'

export function Icon({
  name,
  size = 18,
  ...props
}: {
  name: string
  size?: number
  [key: string]: unknown
}) {
  const Component = Icons[name as keyof typeof Icons] as React.ElementType
  return Component ? (
    <Component size={size} strokeWidth={1.7} aria-hidden="true" {...props} />
  ) : null
}
export function Button({
  children,
  icon,
  kind = '',
  className = '',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { icon?: string; kind?: string }) {
  return (
    <button className={`button ${kind} ${className}`} {...props}>
      {icon && <Icon name={icon} size={16} />}
      {children}
    </button>
  )
}
export function Tool({
  label,
  icon,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; icon: string }) {
  return (
    <button type="button" className="tool" aria-label={label} data-tip={label} {...props}>
      <Icon name={icon} />
    </button>
  )
}
export function Badge({ status }: { status: string }) {
  const tone =
    status === '有阻碍' || status === '待提交'
      ? 'amber'
      : status === '已完成' || status === '已提交'
        ? 'green'
        : ''
  return (
    <span className={`badge ${tone}`}>
      <span className="status-dot" />
      {status}
    </span>
  )
}
export function Avatar({ name, small = false }: { name: string; small?: boolean }) {
  return (
    <span className={`avatar ${small ? 'small' : ''}`}>
      {name === '管理员' ? '管' : name.slice(-1)}
    </span>
  )
}
export function Select({
  value,
  options,
  onChange,
  label,
}: {
  value: string
  options: string[]
  onChange: (v: string) => void
  label: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])
  return (
    <div
      className="select"
      ref={ref}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.preventDefault()
          e.stopPropagation()
          setOpen(false)
        }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault()
          setOpen(true)
          const next =
            (options.indexOf(value) + (e.key === 'ArrowDown' ? 1 : -1) + options.length) %
            options.length
          onChange(options[next])
        }
      }}
    >
      <button
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {value}
        <Icon name="ChevronDown" size={14} />
      </button>
      {open && (
        <div className="select-panel" role="listbox" aria-label={label}>
          {options.map((option) => (
            <button
              type="button"
              key={option}
              role="option"
              aria-selected={option === value}
              onClick={() => {
                onChange(option)
                setOpen(false)
              }}
            >
              {option}
              {option === value && <Icon name="Check" size={14} />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
export function Segments({
  items,
  value,
  onChange,
  label,
}: {
  items: string[]
  value: string
  onChange: (v: string) => void
  label: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [indicator, setIndicator] = useState({ x: 4, width: 0 })
  useLayoutEffect(() => {
    const update = () => {
      const selected = ref.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')
      if (selected) setIndicator({ x: selected.offsetLeft, width: selected.offsetWidth })
    }
    update()
    const observer = new ResizeObserver(update)
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [value, items.join('|')])
  return (
    <div
      className="segments"
      ref={ref}
      role="tablist"
      aria-label={label}
      style={
        {
          '--segment-x': `${indicator.x}px`,
          '--segment-width': `${indicator.width}px`,
        } as React.CSSProperties
      }
    >
      <span className="segment-indicator" aria-hidden="true" />
      {items.map((item) => (
        <button
          type="button"
          role="tab"
          aria-selected={item === value}
          key={item}
          onClick={() => onChange(item)}
          onKeyDown={(event) => {
            if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
            event.preventDefault()
            const index =
              (items.indexOf(item) + (event.key === 'ArrowRight' ? 1 : -1) + items.length) %
              items.length
            onChange(items[index])
            ref.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[index].focus()
          }}
        >
          {item}
        </button>
      ))}
    </div>
  )
}

export function Modal({
  children,
  title,
  onClose,
  drawer = false,
}: {
  children: React.ReactNode
  title: string
  onClose: () => void
  drawer?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    ref.current?.showModal()
  }, [])
  return (
    <dialog
      className={drawer ? 'dialog drawer' : 'dialog'}
      ref={ref}
      aria-label={title}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose()
      }}
    >
      <div className="dialog-inner">
        <header>
          <div>
            <span className="eyebrow">WORK ASSISTANT</span>
            <h2>{title}</h2>
          </div>
          <Tool label="关闭" icon="X" onClick={onClose} />
        </header>
        {children}
      </div>
    </dialog>
  )
}
export function Empty({
  title,
  text,
  action,
}: {
  title: string
  text: string
  action?: React.ReactNode
}) {
  return (
    <div className="empty">
      <div className="empty-art">
        <div />
        <div />
        <Icon name="CircleCheck" size={27} />
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  )
}
export function Header({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children?: React.ReactNode
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  )
}
