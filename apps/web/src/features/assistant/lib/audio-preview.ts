// Only used for the app's bounded recordings. The uploaded original stays intact.
const previews = new WeakMap<File, Promise<Blob>>()

export function recordingPreview(file: File): Promise<Blob> {
  const existing = previews.get(file)
  if (existing) return existing
  const preview = (async () => {
    const context = new OfflineAudioContext(1, 1, 16000)
    const audio = await context.decodeAudioData(await file.arrayBuffer())
    return monoWav(audio)
  })()
  previews.set(file, preview)
  preview.catch(() => previews.delete(file))
  return preview
}

export function monoWav(
  audio: Pick<AudioBuffer, 'length' | 'sampleRate' | 'numberOfChannels' | 'getChannelData'>,
): Blob {
  if (!audio.length || !audio.numberOfChannels || audio.length / audio.sampleRate > 181)
    throw new Error('录音长度无效')
  const data = new ArrayBuffer(44 + audio.length * 2)
  const view = new DataView(data)
  const word = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i))
  }
  word(0, 'RIFF')
  view.setUint32(4, data.byteLength - 8, true)
  word(8, 'WAVE')
  word(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, audio.sampleRate, true)
  view.setUint32(28, audio.sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  word(36, 'data')
  view.setUint32(40, audio.length * 2, true)
  const channels = Array.from({ length: audio.numberOfChannels }, (_, i) => audio.getChannelData(i))
  for (let i = 0; i < audio.length; i++) {
    const sample = Math.max(
      -1,
      Math.min(1, channels.reduce((sum, channel) => sum + channel[i], 0) / channels.length),
    )
    view.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true)
  }
  return new Blob([data], { type: 'audio/wav' })
}
