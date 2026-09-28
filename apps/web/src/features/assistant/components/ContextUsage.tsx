import type { ContextUsage as Usage } from '@paa/api-contracts'
import { capacitySourceLabel } from '@web/utils/model-capacity'
import { X } from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import styles from './ContextUsage.module.css'

const number = (value: number) => value.toLocaleString('zh-CN')
export function contextUsageLabel(usage: Usage | null, unavailable = false) {
  if (!usage) return unavailable ? '暂不可用' : '尚未计算'
  if (usage.state === 'compacting') return '正在压缩上下文'
  if (usage.state === 'retry_wait') return '压缩重试中'
  if (usage.state === 'failed') return '上下文处理未完成'
  if (!usage.contextWindow) return '窗口大小未配置'
  return `约 ${Math.floor((usage.usedTokens / usage.contextWindow) * 100)}%`
}

export function ContextUsage({
  usage,
  unavailable = false,
}: {
  usage: Usage | null
  unavailable?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [hint, setHint] = useState(false)
  const [position, setPosition] = useState({ left: 0, bottom: 0, maxHeight: 400 })
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const id = useId()
  const label = contextUsageLabel(usage, unavailable)
  const percent = usage?.contextWindow ? usage.usedTokens / usage.contextWindow : null
  const visible = open || hint
  useLayoutEffect(() => {
    if (!visible) return
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect()
      if (!rect) return
      const width = open ? 300 : 220
      const above = Math.max(0, rect.top - 20)
      const below = Math.max(0, window.innerHeight - rect.bottom - 20)
      const useAbove = above >= 160 || above >= below
      setPosition({
        left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)),
        bottom: useAbove ? Math.max(12, window.innerHeight - rect.top + 8) : 12,
        maxHeight: useAbove ? above : below,
      })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [visible, open])
  useEffect(() => {
    if (!open) return
    closeButton.current?.focus()
    const outside = (event: PointerEvent) => {
      if (
        !panel.current?.contains(event.target as Node) &&
        !trigger.current?.contains(event.target as Node)
      ) {
        setOpen(false)
        setHint(false)
      }
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  const close = () => {
    setOpen(false)
    trigger.current?.focus()
    setHint(false)
  }
  return (
    <>
      <button
        type="button"
        ref={trigger}
        className={styles.trigger}
        aria-label={`上下文使用情况：${label}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-describedby={hint && !open ? `${id}-hint` : undefined}
        data-active={usage?.state === 'compacting' || usage?.state === 'retry_wait'}
        onPointerEnter={(event) => {
          if (event.pointerType !== 'touch') setHint(true)
        }}
        onPointerLeave={() => setHint(false)}
        onFocus={() => setHint(true)}
        onBlur={() => setHint(false)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            close()
            event.stopPropagation()
          }
        }}
        onClick={() => {
          setOpen(!open)
          setHint(false)
        }}
      >
        <svg
          viewBox="0 0 28 28"
          width="25"
          height="25"
          aria-hidden="true"
          data-known={percent !== null}
        >
          <circle className={styles.track} cx="14" cy="14" r="10" />
          {percent !== null && (
            <circle
              className={styles.used}
              cx="14"
              cy="14"
              r="10"
              pathLength="100"
              strokeDasharray={`${Math.min(100, Math.max(0, percent * 100))} 100`}
            />
          )}
          {percent === null && <circle className={styles.unknown} cx="14" cy="14" r="1.5" />}
        </svg>
      </button>
      {visible &&
        createPortal(
          open ? (
            <div
              ref={panel}
              id={id}
              role="dialog"
              aria-label="上下文使用情况"
              className={styles.panel}
              style={position}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.stopPropagation()
                  close()
                }
              }}
              onBlur={(event) => {
                if (
                  event.relatedTarget &&
                  !event.currentTarget.contains(event.relatedTarget as Node) &&
                  event.relatedTarget !== trigger.current
                ) {
                  setOpen(false)
                  setHint(false)
                }
              }}
            >
              <header>
                <strong>上下文使用情况</strong>
                <button type="button" ref={closeButton} aria-label="关闭上下文详情" onClick={close}>
                  <X size={16} />
                </button>
              </header>
              <div className={styles.value}>
                {percent !== null ? `约 ${Math.floor(percent * 100)}%` : label}
              </div>
              {percent !== null && usage?.state !== 'ready' && (
                <p className={styles.note}>{label}</p>
              )}
              {usage && (
                <>
                  <dl>
                    <div>
                      <dt>当前输入估算</dt>
                      <dd>{number(usage.usedTokens)} tokens</dd>
                    </div>
                    <div>
                      <dt>窗口容量</dt>
                      <dd>
                        {usage.contextWindow ? `${number(usage.contextWindow)} tokens` : '未配置'}
                      </dd>
                    </div>
                    <div>
                      <dt>本次输出预留</dt>
                      <dd>{number(usage.outputReserve)} tokens</dd>
                    </div>
                    {usage.inputLimit != null && usage.inputLimit !== usage.contextWindow && (
                      <div>
                        <dt>服务输入上限</dt>
                        <dd>{number(usage.inputLimit)} tokens</dd>
                      </div>
                    )}
                  </dl>
                  <p className={styles.model}>{usage.model}</p>
                  <p className={styles.caption}>
                    容量来源：
                    {capacitySourceLabel(usage.capacitySource)}
                  </p>
                  {usage.reason && <p className={styles.note}>{usage.reason}</p>}
                  {usage.state === 'ready' &&
                    usage.compactionId &&
                    usage.beforeTokens != null &&
                    usage.afterTokens != null && (
                      <p className={styles.note}>
                        上下文已压缩 · {number(usage.beforeTokens)} → {number(usage.afterTokens)}{' '}
                        tokens
                      </p>
                    )}
                  <p className={styles.caption}>
                    最近一次助手上下文估算，不含未发送的草稿。
                    {usage.contextWindow ? '达到窗口的 90% 时自动压缩。' : ''}
                  </p>
                </>
              )}
              {!usage && (
                <p className={styles.caption}>
                  {unavailable ? '联网恢复后将重新获取。' : '助手开始处理消息后显示用量。'}
                </p>
              )}
            </div>
          ) : (
            <div role="tooltip" id={`${id}-hint`} className={styles.tooltip} style={position}>
              上下文使用情况 · {label}
            </div>
          ),
          document.body,
        )}
    </>
  )
}
