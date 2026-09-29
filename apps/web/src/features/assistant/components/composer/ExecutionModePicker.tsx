import type { ExecutionMode } from '@paa/api-contracts'
import { Check, ChevronDown, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Modal } from '@web/components/overlays/Modal'
import controlsStyles from '../../../../styles/controls.module.css'
import layoutStyles from '../../../../styles/layout.module.css'
import styles from './ExecutionModePicker.module.css'

export const executionModes = [
  { id: 'ask', name: '逐项确认', description: '写入工作或报告前，先由你确认。' },
  { id: 'auto', name: '自动审核', description: '日常操作直接执行，提交和删除需确认。' },
  { id: 'full', name: '自主执行', description: '在你的任务范围内执行，不再逐项确认。' },
] as const

export function ExecutionModePicker({
  value,
  disabled = false,
  acknowledged,
  onChange,
}: {
  value: ExecutionMode
  disabled?: boolean
  acknowledged: boolean
  onChange: (mode: ExecutionMode, acknowledged?: boolean) => void
}) {
  const [position, setPosition] = useState<{ left: number; bottom: number } | null>(null)
  const [confirm, setConfirm] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const options = useRef<(HTMLButtonElement | null)[]>([])
  const id = useId()
  const open = !!position && !disabled
  const name = executionModes.find((mode) => mode.id === value)!.name
  const close = () => {
    setPosition(null)
    trigger.current?.focus()
  }
  const show = () => {
    const rect = trigger.current?.getBoundingClientRect()
    if (rect)
      setPosition({
        left: Math.max(12, Math.min(rect.left, window.innerWidth - 292)),
        bottom: window.innerHeight - rect.top + 8,
      })
  }
  useEffect(() => {
    if (!open) return
    options.current[executionModes.findIndex((mode) => mode.id === value)]?.focus()
    const outside = (event: PointerEvent) => {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !menu.current?.contains(event.target as Node)
      )
        setPosition(null)
    }
    const resize = () => setPosition(null)
    document.addEventListener('pointerdown', outside)
    window.addEventListener('resize', resize)
    return () => {
      document.removeEventListener('pointerdown', outside)
      window.removeEventListener('resize', resize)
    }
  }, [open, value])
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        data-mode={value}
        title={`执行权限：${name}`}
        aria-label={`执行权限：${name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        disabled={disabled}
        onClick={() => (open ? close() : show())}
        onKeyDown={(event) => {
          if (['ArrowUp', 'ArrowDown'].includes(event.key)) {
            event.preventDefault()
            show()
          }
        }}
      >
        {value === 'full' ? (
          <ShieldAlert size={16} aria-hidden="true" />
        ) : (
          <ShieldCheck size={16} aria-hidden="true" />
        )}
        <span>{name}</span>
        <ChevronDown size={12} aria-hidden="true" />
      </button>
      {open &&
        createPortal(
          <div
            ref={menu}
            id={id}
            role="menu"
            aria-label="执行权限"
            className={styles.menu}
            style={position!}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null))
                setPosition(null)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                event.stopPropagation()
                close()
              }
              const index = options.current.indexOf(document.activeElement as HTMLButtonElement)
              const next =
                event.key === 'ArrowDown'
                  ? (index + 1) % 3
                  : event.key === 'ArrowUp'
                    ? (index + 2) % 3
                    : event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                        ? 2
                        : null
              if (next !== null) {
                event.preventDefault()
                options.current[next]?.focus()
              }
            }}
          >
            {executionModes.map((mode, index) => (
              <button
                key={mode.id}
                ref={(element) => {
                  options.current[index] = element
                }}
                type="button"
                role="menuitemradio"
                data-mode={mode.id}
                aria-checked={value === mode.id}
                onClick={() => {
                  close()
                  if (mode.id === 'full' && !acknowledged) setConfirm(true)
                  else onChange(mode.id)
                }}
              >
                <span>
                  {mode.name}
                  <small>{mode.description}</small>
                </span>
                {value === mode.id && <Check size={16} aria-hidden="true" />}
              </button>
            ))}
          </div>,
          document.body,
        )}
      {confirm && (
        <Modal title="开启自主执行" onClose={() => setConfirm(false)}>
          <p>当前会话中，你明确要求的工作和报告操作将直接执行，包括提交与删除，不再逐项确认。</p>
          <p>缺少必要信息时仍会向你提问；可访问的数据和账号权限保持不变。</p>
          <div className={layoutStyles['form-actions']}>
            <button type="button" onClick={() => setConfirm(false)}>
              取消
            </button>
            <button
              type="button"
              disabled={disabled}
              className={controlsStyles.primary}
              onClick={() => {
                setConfirm(false)
                onChange('full', true)
              }}
            >
              开启自主执行
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}
