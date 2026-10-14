import { BriefcaseBusiness, ImagePlus, Paperclip } from 'lucide-react'
import type { usePopover } from '@web/components/overlays/usePopover'
import styles from './MessageComposer.module.css'

export function ComposerAttachmentMenu({
  menu,
  disabled,
  addImages,
  addFiles,
  selectWork,
}: {
  menu: ReturnType<typeof usePopover>
  disabled: boolean
  addImages: () => void
  addFiles: () => void
  selectWork?: () => void
}) {
  return (
    <div
      {...menu.panelProps}
      className={styles['attachment-menu']}
      role="dialog"
      aria-label="添加附件"
    >
      <button disabled={disabled} onClick={addImages}>
        <ImagePlus size={18} />
        <span>
          添加图片<small>上传截图、照片或粘贴图片</small>
        </span>
      </button>
      <button disabled={disabled} onClick={addFiles}>
        <Paperclip size={18} />
        <span>
          添加文件<small>文档、PDF 或语音文件</small>
        </span>
      </button>
      {selectWork && (
        <button disabled={disabled} onClick={selectWork}>
          <BriefcaseBusiness size={18} />
          <span>
            引用工作<small>选择我的工作作为本条消息的参考</small>
          </span>
        </button>
      )}
    </div>
  )
}
