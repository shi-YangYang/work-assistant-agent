import { describe, expect, it } from 'vitest'
import type { Composer } from '../../apps/web/src/audio-capture'
import {
  currentCitation,
  fileKind,
  fileSelectionError,
  updateSendingDraft,
  messageSubmission,
  clipboardImages,
  droppedFiles,
  isHeif,
} from '../../apps/web/src/files'
const file = (name: string, size = 100, type = '') => ({ name, size, type }) as File

describe('document composer', () => {
  it('accepts all supported documents with mixed images and enforces aggregate boundaries', () => {
    for (const extension of ['pdf', 'docx', 'pptx', 'txt', 'json', 'md', 'csv', 'xlsx']) {
      expect(fileKind(file(`项目.${extension.toUpperCase()}`))).toBe('document')
      expect(fileSelectionError([file(`项目.${extension}`), file('photo.png')])).toBe('')
    }
    expect(fileSelectionError(Array.from({ length: 5 }, (_, i) => file(`${i}.txt`)))).toContain(
      '最多 4',
    )
    expect(
      fileSelectionError([file('large.pdf', 16 * 1024 * 1024), file('image.png', 5 * 1024 * 1024)]),
    ).toContain('20 MiB')
    expect(fileSelectionError([file('image.jpg', 5 * 1024 * 1024 + 1)])).toContain('5 MiB')
    expect(fileSelectionError([file('audio.m4a'), file('text.txt'), file('photo.heic')])).toBe('')
    expect(fileSelectionError([file('audio.m4a'), file('audio.mp3')])).toContain('一段语音')
    expect(fileSelectionError([file('audio.wav', 20 * 1024 * 1024 + 1)])).toContain('20 MiB')
    expect(fileSelectionError([file('zero.txt', 0)])).toContain('空文件')
    for (const extension of ['doc', 'ppt', 'xls', 'docm', 'exe'])
      expect(fileSelectionError([file(`old.${extension}`)])).toContain('转换')
  })
  it('late uploads and sends only update their original operation draft', () => {
    const first: Composer = { text: '保留文字', files: [], key: 'original', sending: true }
    expect(updateSendingDraft(first, 'original', { sending: false })).toEqual({
      ...first,
      sending: false,
    })
    expect(updateSendingDraft(first, 'original', { uploading: 'file-1' })?.uploading).toBe('file-1')
    const newer = { ...first, key: 'new', text: '切回后继续编辑' }
    expect(updateSendingDraft(newer, 'original', null)).toBe(newer)
    expect(updateSendingDraft(newer, 'original', { files: [] })).toBe(newer)
    expect(updateSendingDraft(first, 'original', null)).toBeUndefined()
    expect(updateSendingDraft(undefined, 'original', { sending: false })).toBeUndefined()
  })
  it('keeps a citation open across polling object replacements and closes after deletion or reparse', () => {
    const selected = {
      attachmentId: 'file',
      revision: 1,
      ordinal: 3,
      name: '来源',
      location: '第 2 页',
    }
    const polled = { ...selected }
    expect(currentCitation([polled], selected)).toBe(polled)
    expect(currentCitation([], selected)).toBeUndefined()
    expect(currentCitation([{ ...polled, revision: 2 }], selected)).toBeUndefined()
    expect(currentCitation([{ ...polled, attachmentId: 'another' }], selected)).toBeUndefined()
  })
})

it('holds the original message, reply target and uploaded IDs fixed for uncertain result recovery', () => {
  const first: Composer = { text: '原消息', key: 'original', files: [], replyTo: 'original-source' }
  const pending = messageSubmission(first)
  const changed = { ...first, text: '修改后的输入', key: 'new-key', replyTo: 'new-source', pending }
  expect(messageSubmission(changed)).toBe(pending)
  expect(pending).toMatchObject({
    key: 'original',
    body: { text: '原消息', attachmentIds: [], replyTo: 'original-source', newConversation: true },
  })
  expect(messageSubmission({ ...changed, pending: undefined }, 'existing').key).toBe('new-key')
})

it('clipboard only accepts real image files, preserving normal text and never fetching HTML URLs', () => {
  const picture = file('clipboard.png', 120, 'image/png')
  const items = [
    { kind: 'string', type: 'text/html', getAsFile: () => null },
    { kind: 'file', type: 'image/png', getAsFile: () => picture },
    { kind: 'file', type: 'application/pdf', getAsFile: () => file('doc.pdf') },
  ]
  expect(clipboardImages({ items } as unknown as DataTransfer)).toEqual([picture])
  expect(clipboardImages({ items: [items[0]] } as unknown as DataTransfer)).toEqual([])
  expect(droppedFiles({ files: [picture], items: [] } as unknown as DataTransfer).files).toEqual([
    picture,
  ])
  expect(
    droppedFiles({
      items: [{ webkitGetAsEntry: () => ({ isDirectory: true }) }],
    } as unknown as DataTransfer).error,
  ).toContain('文件夹')
  expect(isHeif(file('phone.HEIC'))).toBe(true)
  expect(fileKind(file('voice.mp3'))).toBe('audio')
})
