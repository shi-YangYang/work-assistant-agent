import type { DocumentCitation } from '@paa/api-contracts'
import {
  MAX_ATTACHMENTS,
  MAX_AUDIO_ATTACHMENTS,
  MAX_IMAGE_BYTES,
  MAX_FILE_BYTES,
} from './attachment-limits'

import { inputRules } from '@paa/api-contracts'

const policy = inputRules.attachment
export const fileAccept = undefined

function extensionOf(name: string) {
  const basename = name
    .replaceAll('\\', '/')
    .split('/')
    .pop()!
    .toLowerCase()
    .replace(/[. ]+$/, '')
  return basename.includes('.') ? basename.split('.').pop()! : ''
}

export function blockedFileMessage(name: string) {
  const suffix = extensionOf(name)
  if (policy.blocked.archive.includes(suffix)) return '暂不支持压缩包，请解压后选择需要处理的文件。'
  if (policy.blocked.macro.includes(suffix))
    return '暂不支持含宏文件，请转换为 PDF、DOCX、PPTX、XLSX 或 CSV。'
  if (policy.blocked.program.includes(suffix)) return '暂不支持上传程序、安装包、镜像或编译文件。'
  return ''
}

export function isLegacyOfficeFile(name: string) {
  return policy.legacyOffice.includes(extensionOf(name))
}

export function fileKind(file: Pick<File, 'name' | 'type'>) {
  if (blockedFileMessage(file.name)) return null
  const extension = extensionOf(file.name)
  if (policy.images.includes(extension)) return 'image'
  if (policy.audio.includes(extension)) return 'audio'
  // Unknown suffixes and misleading MIME values remain text candidates.
  return 'document'
}

export function fileSelectionError(files: File[]) {
  const blocked = files.map((file) => blockedFileMessage(file.name)).find(Boolean)
  if (blocked) return blocked
  if (files.some((file) => !file.size)) return '不能添加空文件'
  if (files.length > MAX_ATTACHMENTS) return '每次最多 9 个附件'
  if (files.filter((file) => fileKind(file) === 'audio').length > MAX_AUDIO_ATTACHMENTS)
    return '每次最多 3 段语音，每段最长 3 分钟'
  if (files.some((file) => fileKind(file) === 'image' && file.size > MAX_IMAGE_BYTES))
    return '每张图片不能超过 30 MB'
  if (files.some((file) => fileKind(file) !== 'image' && file.size > MAX_FILE_BYTES))
    return '单个文档或语音文件不能超过 20 MB'
  return ''
}

export function fileSize(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.ceil(bytes / 1024)} KB`
}

export function currentCitation(citations: DocumentCitation[], selected: DocumentCitation | null) {
  return selected
    ? citations.find(
        (citation) =>
          citation.attachmentId === selected.attachmentId &&
          citation.revision === selected.revision &&
          citation.ordinal === selected.ordinal,
      )
    : undefined
}

export function isHeif(file: Pick<File, 'name' | 'type'>) {
  return /\.hei[cf]$/i.test(file.name) || /^image\/hei[cf]$/.test(file.type)
}

export function clipboardImages(data: DataTransfer): File[] {
  return Array.from(data.items)
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null)
}

export function droppedFiles(data: DataTransfer) {
  const items = Array.from(data.items)
  if (items.some((item) => item.webkitGetAsEntry?.()?.isDirectory))
    return { files: [], error: '请添加文件，不支持直接添加文件夹' }
  return { files: Array.from(data.files), error: '' }
}

export function clipboardFiles(data: DataTransfer): File[] {
  return Array.from(data.items)
    .filter((item) => item.kind === 'file')
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null)
}
