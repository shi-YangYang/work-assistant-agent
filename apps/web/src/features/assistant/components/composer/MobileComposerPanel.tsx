import { BriefcaseBusiness, ImagePlus, Paperclip } from 'lucide-react'
import type { ReactNode } from 'react'
import styles from './MobileComposerPanel.module.css'

export function MobileComposerPanel({
  id,
  mobile,
  open,
  disabled,
  addImages,
  addFiles,
  selectWork,
  context,
  reasoning,
  execution,
}: {
  id: string
  mobile: boolean
  open: boolean
  disabled: boolean
  addImages: () => void
  addFiles: () => void
  selectWork?: () => void
  context: ReactNode
  reasoning?: ReactNode
  execution?: ReactNode
}) {
  return (
    <div
      id={id}
      className={styles.panel}
      role={mobile ? 'region' : undefined}
      aria-label={mobile ? '更多功能' : undefined}
      hidden={mobile && !open}
    >
      {mobile && (
        <>
          <button
            className={styles.entry}

            type="button"
            disabled={disabled}
            onClick={addImages}
          >
            <ImagePlus size={23} />
            <span>添加图片</span>
          </button>
          <button
            className={styles.entry}

            type="button"
            disabled={disabled}
            onClick={addFiles}
          >
            <Paperclip size={23} />
            <span>添加文件</span>
          </button>
          {selectWork && (
            <button
              className={styles.entry}

              type="button"
              disabled={disabled}
              onClick={selectWork}
            >
              <BriefcaseBusiness size={23} />
              <span>引用工作</span>
            </button>
          )}
        </>
      )}
      <div className={styles.context}>{context}</div>
      <div className={styles.reasoning}>{reasoning}</div>
      <div className={styles.execution}>{execution}</div>
    </div>
  )
}
