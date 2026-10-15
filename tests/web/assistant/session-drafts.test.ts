import type { Identity } from '@paa/api-contracts'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  Composer,
  PendingFile,
} from '../../../apps/web/src/features/assistant/lib/audio-capture'
import {
  AttachmentUploads,
  attachmentsReady,
} from '../../../apps/web/src/features/assistant/lib/attachment-uploads'
import { composerDraftLifecycle } from '../../../apps/web/src/features/assistant/lib/composer-drafts'
import { SessionDrafts } from '../../../apps/web/src/lib/session-drafts'
const identity = (company = 'company', id = 'member', role = 'employee') =>
  ({ company: { id: company }, member: { id, role } }) as Identity
const composer = { text: '未发送文字', files: [], key: 'original', sending: true }
afterEach(() => vi.restoreAllMocks())
describe('verified same-page chat recovery', () => {
  it.each(['upload', 'message'] as const)(
    'discards interrupted direct audio during %s while restoring the ordinary draft',
    (phase) => {
      const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
      const vault = new SessionDrafts(composerDraftLifecycle)
      vault.resume(identity())
      const oldWriter = vault.writer()
      const notes: PendingFile = {
        id: 'notes',
        file: new File(['notes'], 'notes.py'),
        url: 'blob:notes',
        attachment: {
          id: 'notes',
          kind: 'document',
          name: 'notes.py',
          mime: 'text/plain',
          size: 5,
          duration: null,
          url: '/notes',
        },
      }
      const voice: PendingFile = {
        id: 'voice',
        file: new File(['voice'], 'voice.webm'),
        url: 'blob:voice',
        recorded: true,
        directSend: true,
        ...(phase === 'message'
          ? {
              attachment: {
                id: 'uncertain-voice',
                kind: 'audio' as const,
                name: 'voice.webm',
                mime: 'audio/webm',
                size: 5,
                duration: 1,
                url: '/voice',
              },
            }
          : {}),
      }
      oldWriter('composer:first', { ...composer, files: [notes, voice] })
      vault.suspend()
      // Session expiry precedes the old send catch/finally callbacks.
      oldWriter('composer:first', { ...composer, files: [] })
      vault.resume(identity())
      const upload = vi.fn()
      const remove = vi.fn()
      const manager = new AttachmentUploads({ upload, remove })
      manager.bind('company:member:employee', vault.writer())
      manager.sync(vault.getSnapshot())
      const restored = vault.getSnapshot()['composer:first'] as Composer
      expect(restored).toMatchObject({
        text: composer.text,
        sending: false,
        files: [{ ...notes, uploadState: 'ready' }],
      })
      expect(attachmentsReady(restored.files)).toBe(true)
      expect(upload).not.toHaveBeenCalled()
      expect(remove).not.toHaveBeenCalled()
      expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:voice')
      manager.pause()
    },
  )
  it('keeps only chat input through expiration and blocks late upload/recording/settings callbacks', () => {
    const vault = new SessionDrafts(composerDraftLifecycle)
    vault.resume(identity())
    const write = vault.writer()
    write('composer:new', composer)
    write('modelServices', { key: 'sensitive-key' })
    write('report:1', { text: 'report' })
    vault.suspend()
    write('composer:new', { ...composer, text: 'late file callback' })
    vault.resume(identity())
    expect(vault.getSnapshot()).toEqual({
      'composer:new': { ...composer, sending: false, uploading: undefined },
    })
    vault.writer()('composer:new', { ...composer, text: '继续编辑' })
    expect(vault.getSnapshot()['composer:new']).toMatchObject({ text: '继续编辑' })
  })
  it.each([
    identity('other'),
    identity('company', 'other'),
    identity('company', 'member', 'admin'),
  ])('discards all drafts for a changed company/member/role', (next) => {
    const vault = new SessionDrafts(composerDraftLifecycle)
    vault.resume(identity())
    const old = vault.writer()
    old('composer:new', composer)
    vault.suspend()
    vault.resume(next)
    old('composer:new', composer)
    expect(vault.getSnapshot()).toEqual({})
  })
  it('explicit logout and lost access clear input while new authorized writers remain usable', () => {
    const vault = new SessionDrafts(composerDraftLifecycle)
    vault.resume(identity())
    const old = vault.writer()
    old('composer:new', composer)
    vault.clear()
    old('composer:new', composer)
    expect(vault.getSnapshot()).toEqual({})
    vault.resume(identity())
    expect(vault.getSnapshot()).toEqual({})
    vault.writer()('composer:new', composer)
    expect(vault.getSnapshot()['composer:new']).toEqual(composer)
  })
})
