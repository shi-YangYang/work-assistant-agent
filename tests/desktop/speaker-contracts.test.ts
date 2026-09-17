import { describe, expect, it } from 'vitest'
import {
  validSpeakerRequest,
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
      isSpeakerStatus({ ...status, speakers: [{ id: 'speaker_00', name: 'x'.repeat(41) }] }),
    ).toBe(false)
    expect(isSpeakerStatus({ ...status, model: { state: 'preparing' } })).toBe(false)
    expect(isSpeakerStatus({ ...status, speakers: [null] })).toBe(false)
  })
})
