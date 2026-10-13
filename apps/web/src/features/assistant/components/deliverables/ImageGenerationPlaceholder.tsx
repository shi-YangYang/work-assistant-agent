import type { ImageGenerationSlot } from '@paa/api-contracts'
import { Check, CircleAlert, CircleX, ImageIcon } from 'lucide-react'
import { ImageGenerationDots } from './ImageGenerationDots'
import styles from './ImageGenerationPlaceholder.module.css'

const labels: Record<ImageGenerationSlot['state'], string> = {
  queued: '等待生成',
  generating: '正在生成',
  ready: '加载图片…',
  failed: '生成失败',
  unknown: '结果待确认',
  interrupted: '生成已中断',
  not_started: '未生成',
  cancelled: '已取消',
}

export function ImageGenerationPlaceholder({ slot }: { slot: ImageGenerationSlot }) {
  const active = slot.state === 'generating'
  const staticPreview = slot.state === 'ready' || slot.state === 'cancelled'
  const PlaceholderIcon = slot.state === 'cancelled' ? CircleX : ImageIcon
  const label = labels[slot.state]
  return (
    <div
      className={styles.placeholder}
      data-active={active}
      role="status"
      aria-label={`第 ${slot.operation} 张图片：${label}`}
    >
      <div className={`${styles.surface} ${staticPreview ? styles.loading : ''}`}>
        {staticPreview ? (
          <PlaceholderIcon size={24} strokeWidth={1.5} aria-hidden="true" />
        ) : (
          <ImageGenerationDots active={active} flat={slot.state === 'queued'} />
        )}
        {!staticPreview && slot.width && slot.height && (
          <span className={styles.dimensions}>
            {slot.width} × {slot.height}
          </span>
        )}
      </div>
      <ImageGenerationCaption state={slot.state} />
    </div>
  )
}

export function ImageGenerationCaption({
  state,
}: {
  state: ImageGenerationSlot['state'] | 'complete'
}) {
  const active = state === 'generating'
  return (
    <div className={styles.caption} data-active={active}>
      {state === 'complete' ? (
        <Check size={14} aria-hidden="true" />
      ) : ['ready', 'queued', 'cancelled'].includes(state) ? null : state === 'generating' ? (
        <span className={styles.mark} aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </span>
      ) : (
        <CircleAlert size={14} aria-hidden="true" />
      )}
      <span key={state} className={styles.label}>
        {state === 'complete' ? '已生成' : labels[state]}
      </span>
    </div>
  )
}
