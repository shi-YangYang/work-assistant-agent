import type { DocumentCitation } from '@paa/api-contracts'
import type { Composer } from './audio-capture'

const documents = new Set(['pdf', 'docx', 'pptx', 'txt', 'json', 'md', 'csv'])
const images = new Set(['jpg', 'jpeg', 'png', 'webp'])
const audio = new Set(['wav', 'webm', 'mp4', 'm4a', 'aac'])
export const fileAccept =
  '.pdf,.docx,.pptx,.txt,.json,.md,.csv,.jpg,.jpeg,.png,.webp,.wav,.webm,.mp4,.m4a,.aac'
export function fileKind(file: Pick<File, 'name' | 'type'>) {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (documents.has(extension)) return 'document'
  if (images.has(extension) || ['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
    return 'image'
  if (
    audio.has(extension) ||
    ['audio/wav', 'audio/webm', 'audio/mp4', 'audio/aac'].includes(file.type)
  )
    return 'audio'
  return null
}
export function fileSelectionError(files: File[]) {
  if (files.some((file) => !fileKind(file)))
    return '支持 PDF、DOCX、PPTX、TXT、JSON、MD、CSV、图片和语音；旧版 Office、Excel 或含宏文件请先转换。'
  if (files.some((file) => !file.size)) return '不能添加空文件'
  if (files.some((file) => fileKind(file) === 'audio')) {
    if (files.length !== 1 || files[0].size > 20 * 1024 * 1024)
      return '每次一段语音，最长 3 分钟、20 MiB，请先移除其他附件'
  } else if (files.length > 4 || files.reduce((sum, file) => sum + file.size, 0) > 20 * 1024 * 1024)
    return '每次最多 4 个文档或图片，合计不超过 20 MiB'
  if (files.some((file) => fileKind(file) === 'image' && file.size > 5 * 1024 * 1024))
    return '每张图片不能超过 5 MiB'
  return ''
}
export function fileSize(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MiB`
    : `${Math.ceil(bytes / 1024)} KiB`
}
export function updateSendingDraft(
  previous: Composer | undefined,
  key: string,
  update: Partial<Composer> | null,
) {
  if (previous?.key !== key) return previous
  return update === null ? undefined : { ...previous, ...update }
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

export function messageSubmission(
  composer: Composer,
  conversationId?: string,
): NonNullable<Composer['pending']> {
  if (composer.pending) return composer.pending
  return {
    key: composer.key,
    body: {
      conversationId,
      ...(!conversationId ? { newConversation: true } : {}),
      text: composer.text,
      attachmentIds: composer.files.map((file) => {
        if (!file.attachment) throw new Error('附件尚未上传完成')
        return file.attachment.id
      }),
      replyTo: composer.replyTo ?? null,
    },
  }
}
