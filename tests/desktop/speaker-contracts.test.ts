import { describe, expect, it } from 'vitest'
import {
  validSpeakerRequest,
  validSpeakerName,
  normalizeSpeakerName,
  speakerNameLength,
  isSpeakerStatus,
} from '../../apps/desktop/src/shared/speaker-contracts'

const meetingId = '64450a04-4d7d-4efa-a827-e63ea374f437'
describe('speaker IPC boundaries', () => {
  it('accepts bounded meeting-local edits and rejects former model download/import APIs', () => {
    expect(validSpeakerRequest({ action: 'start', meetingId })).toBe(true)
    const edit = {
      action: 'assign',
      meetingId,
      generation: 'legacy',
      revision: 1,
      speakerId: null,
      segmentId: 'source-segment',
    }
    expect(validSpeakerRequest(edit)).toBe(true)
    expect(validSpeakerRequest({ ...edit, speakerId: '../someone' })).toBe(false)
    expect(validSpeakerRequest({ ...edit, revision: -1 })).toBe(false)
    expect(validSpeakerRequest({ ...edit, other: 'unexpected' })).toBe(false)
    expect(validSpeakerRequest({ action: 'prepare', token: 'secret' })).toBe(false)
    expect(validSpeakerRequest({ action: 'import', path: '/tmp' })).toBe(false)
    expect(validSpeakerRequest({ action: '__proto__', meetingId })).toBe(false)
    expect(
      validSpeakerRequest({
        action: 'rename',
        meetingId,
        generation: 'legacy',
        revision: 1,
        speakerId: 'speaker_00',
        name: '张三\n李四',
      }),
    ).toBe(false)
  })
  it.each([
    '中'.repeat(40),
    '中'.repeat(41),
    'a'.repeat(100),
    '😀'.repeat(100),
    '张三😀'.repeat(33),
    '\ufeff',
    '\ufeff' + '中'.repeat(99),
    '\u3000' + '😀'.repeat(100) + '\u00a0',
  ])('accepts a legal Unicode name through request and state contracts: %s', (name) => {
    expect(validSpeakerName(name)).toBe(true)
    expect(
      validSpeakerRequest({
        action: 'rename',
        meetingId,
        generation: 'legacy',
        revision: 1,
        speakerId: 'speaker_00',
        name,
      }),
    ).toBe(true)
    expect(
      isSpeakerStatus({
        meetingId,
        generation: 'legacy',
        state: 'completed',
        revision: 1,
        device: 'cpu',
        error: null,
        speakers: [{ id: 'speaker_00', name }],
        model: { state: 'ready', error: null },
        progress: '',
      }),
    ).toBe(true)
  })
  it.each([
    '😀'.repeat(101),
    'a'.repeat(101),
    '\ufeff' + '中'.repeat(100),
    '张三\n李四',
    '名字\u0085',
    '名字\u2028',
    ' ',
  ])('rejects invalid names consistently: %s', (name) => {
    expect(validSpeakerName(name)).toBe(false)
    expect(
      validSpeakerRequest({
        action: 'rename',
        meetingId,
        generation: 'legacy',
        revision: 1,
        speakerId: 'speaker_00',
        name,
      }),
    ).toBe(false)
  })
  it('normalizes the complete legacy Python whitespace set and preserves FEFF name content', () => {
    const whitespace = [
      0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680, 0x2000,
      0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028,
      0x2029, 0x202f, 0x205f, 0x3000,
    ]
    for (const code of whitespace) {
      const char = String.fromCodePoint(code)
      const name = `${char}${'😀'.repeat(100)}${char}`
      expect(normalizeSpeakerName(name)).toBe('😀'.repeat(100))
      expect(speakerNameLength(name)).toBe(100)
      // Control characters remain forbidden even when they are at the edges.
      expect(validSpeakerName(name)).toBe(
        (code >= 0xa0 && code !== 0x2028 && code !== 0x2029) || code === 0x20,
      )
      expect(normalizeSpeakerName(char)).toBe('')
      expect(speakerNameLength(char)).toBe(0)
      expect(validSpeakerName(char)).toBe(false)
    }
    expect(normalizeSpeakerName(' \ufeff张三\ufeff ')).toBe('\ufeff张三\ufeff')
    expect(speakerNameLength('\ufeff')).toBe(1)
    expect(speakerNameLength('\ufeff' + '😀'.repeat(100))).toBe(101)
    expect(normalizeSpeakerName('\u00a0张\u3000三\u00a0')).toBe('张\u3000三')
  })
  it('rejects malformed core responses', () => {
    const status = {
      meetingId,
      generation: 'legacy',
      state: 'completed',
      revision: 1,
      device: 'mps',
      error: null,
      speakers: [{ id: 'speaker_00', name: '说话人 A' }],
      model: { state: 'ready', error: null },
      progress: '',
    }
    expect(isSpeakerStatus(status)).toBe(true)
    expect(
      isSpeakerStatus({ ...status, speakers: [{ id: 'speaker_00', name: 'x'.repeat(100) }] }),
    ).toBe(true)
    expect(
      isSpeakerStatus({ ...status, speakers: [{ id: 'speaker_00', name: 'x'.repeat(101) }] }),
    ).toBe(false)
    expect(isSpeakerStatus({ ...status, model: { state: 'preparing' } })).toBe(false)
    expect(isSpeakerStatus({ ...status, speakers: [null] })).toBe(false)
  })
})
