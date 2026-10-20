import { expect, it, vi } from 'vitest'
import type { Attachment } from '@paa/api-contracts'
import type { Composer } from '../../../apps/web/src/features/assistant/lib/audio-capture'
import {
  AttachmentUploads,
  attachmentsReady,
} from '../../../apps/web/src/features/assistant/lib/attachment-uploads'
import type { DraftStore } from '../../../apps/web/src/lib/workspace'
import { numberedFiles } from '../../../apps/web/src/features/assistant/lib/attachment-names'
import { ApiError } from '../../../apps/web/src/api/client'

const attachment = (id: string): Attachment => ({
  id,
  kind: 'document',
  duration: null,
  name: id + '.py',
  mime: 'text/plain',
  size: 3,
  url: '/' + id,
})
const file = (id: string) => ({ id, file: new File(['abc'], id + '.py'), url: 'blob:' + id })
const flush = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve()
}
function setup() {
  const pending: {
    resolve: (a: Attachment) => void
    reject: (e: Error) => void
    signal: AbortSignal
  }[] = []
  const upload = vi.fn(
    (_file: File, signal: AbortSignal) =>
      new Promise<Attachment>((resolve, reject) => pending.push({ resolve, reject, signal })),
  )
  const remove = vi.fn(async () => {})
  const manager = new AttachmentUploads({ upload, remove })
  const drafts: DraftStore = { 'composer:first': { key: 'key', text: 'draft', files: [] } }
  const writer = (key: string, value: unknown) => {
    drafts[key] = typeof value === 'function' ? value(drafts[key]) : value
  }
  manager.bind('account', writer)
  const current = () => drafts['composer:first'] as Composer
  const sync = () => manager.sync(drafts)
  return { manager, pending, upload, remove, drafts, writer, current, sync }
}

it('uploads two at a time, starts queued files immediately, and retries only the failed item', async () => {
  const h = setup()
  h.current().files = [file('a'), file('b'), file('c')]
  h.sync()
  expect(h.upload).toHaveBeenCalledTimes(2)
  expect(h.current().files.map((f) => f.uploadState)).toEqual(['uploading', 'uploading', undefined])
  expect(attachmentsReady(h.current().files)).toBe(false)
  h.pending[0].resolve(attachment('a'))
  await flush()
  h.sync()
  expect(h.upload).toHaveBeenCalledTimes(3)
  h.pending[1].reject(new Error('network'))
  h.pending[2].resolve(attachment('c'))
  await flush()
  h.sync()
  expect(h.current().files[1].failed).toBe(true)
  h.manager.retry('b')
  expect(h.upload).toHaveBeenCalledTimes(4)
  h.pending[3].resolve(attachment('b'))
  await flush()
  h.sync()
  expect(attachmentsReady(h.current().files)).toBe(true)
  h.sync()
  expect(h.upload).toHaveBeenCalledTimes(4)
})

it.each([
  [507, 'storage_full', '文件存储空间不足，请稍后重试或联系管理员。'],
  [429, 'upload_busy', '上传服务繁忙，请稍后重试。'],
] as const)(
  'keeps a failed upload recoverable with a clear %s message',
  async (status, code, message) => {
    const h = setup()
    h.current().files = [file('a')]
    h.sync()
    h.pending[0].reject(new ApiError(status, code, '服务暂时不可用', 'server'))
    await flush()
    h.sync()
    expect(h.current().files[0].uploadError).toBe(message)
    expect(attachmentsReady(h.current().files)).toBe(false)
    expect(h.upload).toHaveBeenCalledTimes(1)
    h.manager.retry('a')
    h.pending[1].resolve(attachment('a'))
    await flush()
    expect(attachmentsReady(h.current().files)).toBe(true)
  },
)

it('removes queued/inflight/ready files and cleans late results without resurrecting drafts', async () => {
  const h = setup()
  h.current().files = [file('a'), file('b'), file('c')]
  h.sync()
  h.current().files = [h.current().files[1]]
  h.sync()
  expect(h.pending[0].signal.aborted).toBe(true)
  h.pending[0].resolve(attachment('a'))
  h.pending[1].resolve(attachment('b'))
  await flush()
  h.sync()
  expect(h.remove).toHaveBeenCalledWith('a')
  expect(h.current().files.map((f) => f.id)).toEqual(['b'])
  expect(h.upload).toHaveBeenCalledTimes(2)
  h.current().files = []
  h.sync()
  expect(h.remove).toHaveBeenCalledWith('b')
})

it('retains uploaded IDs through navigation/draft edits and never deletes uncertain or accepted sends', async () => {
  const h = setup()
  h.current().files = [file('a')]
  h.sync()
  h.current().text = 'edited while uploading'
  h.current().key = 'new-key'
  h.pending[0].resolve(attachment('a'))
  await flush()
  h.sync()
  expect(h.current().text).toBe('edited while uploading')
  h.current().sending = true
  h.sync()
  delete h.drafts['composer:first']
  h.sync()
  expect(h.remove).not.toHaveBeenCalled()
  expect(h.upload).toHaveBeenCalledTimes(1)
})

it('pauses requests at session boundaries and ignores direct-recording files', async () => {
  const h = setup()
  h.current().files = [file('a'), { ...file('voice'), directSend: true }]
  h.sync()
  expect(h.upload).toHaveBeenCalledTimes(1)
  h.manager.pause()
  expect(h.pending[0].signal.aborted).toBe(true)
  const before = h.current().files[0]
  h.pending[0].resolve(attachment('old'))
  await flush()
  expect(h.current().files[0]).toBe(before)
  h.manager.bind('next-account', vi.fn())
  h.manager.sync({})
  expect(h.upload).toHaveBeenCalledTimes(1)
})

it('uploads duplicate selections separately and removes only the selected attachment', async () => {
  const h = setup()
  const original = new File(['identical'], 'file.txt')
  h.current().files = numberedFiles([original, original], []).map((file, index) => ({
    id: String(index),
    file,
    url: 'blob:' + index,
  }))
  h.sync()
  expect(h.upload.mock.calls.map(([file]) => file.name)).toEqual(['file.txt', 'file (2).txt'])
  h.pending[0].resolve(attachment('first'))
  h.pending[1].resolve(attachment('second'))
  await flush()
  h.sync()
  h.current().files = [h.current().files[1]]
  h.sync()
  expect(h.remove).toHaveBeenCalledExactlyOnceWith('first')
  expect(h.current().files[0].attachment?.id).toBe('second')
  expect(attachmentsReady(h.current().files)).toBe(true)
})
