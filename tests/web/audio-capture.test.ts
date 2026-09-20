import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Composer } from '../../apps/web/src/features/assistant/lib/audio-capture'
import {
  appendRecordedFile,
  AudioCapture,
  microphoneError,
} from '../../apps/web/src/features/assistant/lib/audio-capture'
import { monoWav, recordingPreview } from '../../apps/web/src/features/assistant/lib/audio-preview'

class ControlledRecorder {
  static instances: ControlledRecorder[] = []
  static failure = ''
  static isTypeSupported() {
    return true
  }
  state = 'inactive'
  mimeType = 'audio/webm'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() {
    if (ControlledRecorder.failure === 'constructor') throw new Error('construction failed')
    ControlledRecorder.instances.push(this)
  }
  start() {
    if (ControlledRecorder.failure === 'start') throw new Error('start failed')
    this.state = 'recording'
  }
  stop() {
    this.state = 'inactive'
    // Browser stop/data events arrive later, independently from stop().
  }
}

function deferredStream() {
  let resolve!: (stream: MediaStream) => void
  const promise = new Promise<MediaStream>((done) => {
    resolve = done
  })
  const tracks = [{ stop: vi.fn() }, { stop: vi.fn() }]
  const stream = { getTracks: () => tracks } as unknown as MediaStream
  return { promise, resolve: () => resolve(stream), tracks }
}
function callbacks() {
  return { state: vi.fn(), error: vi.fn(), file: vi.fn() }
}
beforeEach(() => {
  ControlledRecorder.instances = []
  ControlledRecorder.failure = ''
  vi.stubGlobal('MediaRecorder', ControlledRecorder)
})
afterEach(() => vi.unstubAllGlobals())

describe('asynchronous microphone ownership', () => {
  it('stops every late track after page unmount without constructing a recorder', async () => {
    const request = deferredStream()
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => request.promise } })
    const events = callbacks()
    const capture = new AudioCapture(events)
    const starting = capture.start()
    capture.dispose()
    request.resolve()
    await starting
    expect(request.tracks.every((track) => track.stop.mock.calls.length === 1)).toBe(true)
    expect(ControlledRecorder.instances).toHaveLength(0)
    expect(events.state.mock.calls).toEqual([['requesting']])
    expect(events.file).not.toHaveBeenCalled()
  })

  it('guards double clicks and cancellation while a newer permission request is active', async () => {
    const old = deferredStream()
    const current = deferredStream()
    const getUserMedia = vi
      .fn()
      .mockReturnValueOnce(old.promise)
      .mockReturnValueOnce(current.promise)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
    const events = callbacks()
    const capture = new AudioCapture(events)
    const first = capture.start()
    await capture.start()
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    capture.stop()
    const second = capture.start()
    current.resolve()
    await second
    old.resolve()
    await first
    expect(ControlledRecorder.instances).toHaveLength(1)
    expect(events.state.mock.calls.at(-1)).toEqual(['recording'])
    expect(current.tracks.every((track) => track.stop.mock.calls.length === 0)).toBe(true)
    expect(old.tracks.every((track) => track.stop.mock.calls.length === 1)).toBe(true)
    capture.dispose()
  })

  it.each(['constructor', 'start'])(
    'cleans acquired tracks on %s failure and allows retry',
    async (failure) => {
      const request = deferredStream()
      vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => request.promise } })
      const events = callbacks()
      const capture = new AudioCapture(events)
      ControlledRecorder.failure = failure
      const starting = capture.start()
      request.resolve()
      await starting
      expect(request.tracks.every((track) => track.stop.mock.calls.length > 0)).toBe(true)
      expect(events.state.mock.calls.at(-1)).toEqual(['idle'])
      expect(events.error).toHaveBeenCalledTimes(1)
      expect(events.file).not.toHaveBeenCalled()
      ControlledRecorder.failure = ''
      await capture.start()
      expect(events.state.mock.calls.at(-1)).toEqual(['recording'])
      capture.dispose()
    },
  )

  it('preserves final audio on navigation without letting old events stop a later recording', async () => {
    const old = deferredStream()
    const current = deferredStream()
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise),
      },
    })
    const oldEvents = callbacks()
    let draft: Composer = { text: '录音前的文字', key: 'old-key', files: [] }
    oldEvents.file.mockImplementation((file: File) => {
      draft = appendRecordedFile(draft, file)
    })
    const oldCapture = new AudioCapture(oldEvents)
    const first = oldCapture.start()
    old.resolve()
    await first
    const oldRecorder = ControlledRecorder.instances[0]
    oldCapture.dispose()
    const newEvents = callbacks()
    const newCapture = new AudioCapture(newEvents)
    const second = newCapture.start()
    current.resolve()
    await second
    draft = { ...draft, text: '离开后刚输入的新文字', replyTo: 'new-source' }
    oldRecorder.ondataavailable?.({ data: new Blob(['captured audio']) })
    oldRecorder.onstop?.()
    oldRecorder.onerror?.()
    oldRecorder.onstop?.()
    expect(oldEvents.file).toHaveBeenCalledTimes(1)
    expect(await oldEvents.file.mock.calls[0][0].text()).toBe('captured audio')
    expect(draft.text).toBe('离开后刚输入的新文字')
    expect(draft.replyTo).toBe('new-source')
    expect(draft.files).toHaveLength(1)
    URL.revokeObjectURL(draft.files[0].url)
    expect(oldEvents.state.mock.calls).toEqual([['requesting'], ['recording']])
    expect(newEvents.state.mock.calls.at(-1)).toEqual(['recording'])
    expect(current.tracks.every((track) => track.stop.mock.calls.length === 0)).toBe(true)
    expect(ControlledRecorder.instances[1].state).toBe('recording')
    newCapture.dispose()
  })
})

it.each([
  ['NotAllowedError', '权限'],
  ['NotFoundError', '未找到麦克风'],
  ['NotReadableError', '占用'],
])('explains microphone %s with a usable alternative', (name, expected) => {
  const error = new DOMException('private device text', name)
  expect(microphoneError(error)).toContain(expected)
  expect(microphoneError(error)).toContain('文字')
  expect(microphoneError(error)).not.toContain('private device')
})

it('stops at the remaining mixed-attachment budget without discarding recorded content', async () => {
  const request = deferredStream()
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => request.promise } })
  const events = callbacks()
  const capture = new AudioCapture(events)
  const starting = capture.start(10)
  request.resolve()
  await starting
  const recorder = ControlledRecorder.instances[0]
  recorder.ondataavailable?.({ data: new Blob(['captured bytes']) })
  expect(recorder.state).toBe('inactive')
  expect(events.error).toHaveBeenCalledWith(expect.stringContaining('容量上限'))
  recorder.onstop?.()
  expect(events.file).toHaveBeenCalledOnce()
  expect(events.file.mock.calls[0][0].size).toBe(14)
})

it('writes a finite WAV duration and bounded mono PCM for local recording playback', async () => {
  const channels = [new Float32Array([-2, -0.5, 0.25, 2]), new Float32Array([-2, 0.5, 0.75, 2])]
  const wav = monoWav({
    length: 4,
    sampleRate: 16000,
    numberOfChannels: 2,
    getChannelData: (i) => channels[i],
  })
  const buffer = await wav.arrayBuffer()
  const header = new DataView(buffer)
  expect(wav.type).toBe('audio/wav')
  expect(new TextDecoder().decode(buffer.slice(0, 4))).toBe('RIFF')
  expect(header.getUint32(4, true)).toBe(buffer.byteLength - 8)
  expect(header.getUint16(22, true)).toBe(1)
  expect(header.getUint32(40, true) / header.getUint32(28, true)).toBe(4 / 16000)
  expect([44, 46, 48, 50].map((i) => header.getInt16(i, true))).toEqual([-32768, 0, 16383, 32767])
})

it('reuses a local recording preview without uploading or replacing the original', async () => {
  const decode = vi.fn().mockResolvedValue({
    length: 16000,
    sampleRate: 16000,
    numberOfChannels: 1,
    getChannelData: () => new Float32Array(16000),
  })
  vi.stubGlobal(
    'OfflineAudioContext',
    class {
      decodeAudioData = decode
    },
  )
  const file = new File(['original recorded bytes'], 'voice.webm', { type: 'audio/webm' })
  const first = recordingPreview(file)
  const second = recordingPreview(file)
  expect(first).toBe(second)
  expect((await first).size).toBe(32044)
  expect(decode).toHaveBeenCalledOnce()
  expect(await file.text()).toBe('original recorded bytes')
})
