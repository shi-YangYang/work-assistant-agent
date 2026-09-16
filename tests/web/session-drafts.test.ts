import { describe, expect, it } from 'vitest'
import type { Identity } from '@paa/api-contracts'
import { SessionDrafts } from '../../apps/web/src/session-drafts'
const identity = (company = 'company', id = 'member', role = 'employee') =>
  ({ company: { id: company }, member: { id, role, mustChangePassword: false } }) as Identity
const composer = { text: '未发送文字', files: [], key: 'original', sending: true }
describe('verified same-page chat recovery', () => {
  it('keeps only chat input through expiration and blocks late upload/recording/settings callbacks', () => {
    const vault = new SessionDrafts()
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
    const vault = new SessionDrafts()
    vault.resume(identity())
    const old = vault.writer()
    old('composer:new', composer)
    vault.suspend()
    vault.resume(next)
    old('composer:new', composer)
    expect(vault.getSnapshot()).toEqual({})
  })
  it('explicit logout and lost access clear input while new authorized writers remain usable', () => {
    const vault = new SessionDrafts()
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
