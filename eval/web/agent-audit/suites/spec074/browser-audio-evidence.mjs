// Compare actual browser recording with the synthetic microphone fixture; no ASR/model calls.
import { chromium } from 'playwright'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
const root = resolve('artifacts/spec074/20261017-real-audit')
const browser = await chromium.launch()
try {
  const page = await browser.newPage()
  const decoded = await page.evaluate(
    async ([reference, actual]) => {
      const decode = async (text) => {
        const audio = new AudioContext({ sampleRate: 16000 })
        const bytes = Uint8Array.from(atob(text), (c) => c.charCodeAt(0))
        const buffer = await audio.decodeAudioData(bytes.buffer)
        const pcm = Array.from(buffer.getChannelData(0))
        await audio.close()
        return { sampleRate: buffer.sampleRate, duration: buffer.duration, pcm }
      }
      return { reference: await decode(reference), actual: await decode(actual) }
    },
    [
      readFileSync(root + '/materials/audio.wav').toString('base64'),
      readFileSync(root + '/browser/B04-readback/actual-recording.webm').toString('base64'),
    ],
  )
  const average = (input) => {
    const result = []
    for (let i = 0; i < input.length - 16; i += 16)
      result.push(input.slice(i, i + 16).reduce((a, b) => a + b, 0) / 16)
    return result
  }
  const reference = average(decoded.reference.pcm)
  const actual = average(decoded.actual.pcm)
  let best = { correlation: -1, offsetMs: 0 }
  for (let offset = 0; offset < reference.length; offset++) {
    let xy = 0,
      xx = 0,
      yy = 0
    for (let i = 0; i < actual.length; i++) {
      const a = actual[i],
        b = reference[(i + offset) % reference.length]
      xy += a * b
      xx += a * a
      yy += b * b
    }
    const correlation = xy / Math.sqrt(xx * yy)
    if (correlation > best.correlation) best = { correlation, offsetMs: offset }
  }
  const dir = root + '/browser/B04-readback'
  writeFileSync(
    dir + '/recording.pcm-f32le',
    Buffer.from(new Float32Array(decoded.actual.pcm).buffer),
  )
  const result = {
    referenceSeconds: decoded.reference.duration,
    recordedSeconds: decoded.actual.duration,
    sampleRate: decoded.actual.sampleRate,
    cyclicCrossCorrelationAt1000Hz: best,
    note: 'A shortened recording is not a full-sentence ASR accuracy sample; compare the recorded bytes, not only the source WAV.',
  }
  writeFileSync(dir + '/audio-evidence.json', JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} finally {
  await browser.close()
}
