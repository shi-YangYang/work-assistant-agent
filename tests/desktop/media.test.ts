import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { afterEach, expect, it, vi } from 'vitest'
import { byteRange, serveMedia } from '../../src/desktop/media'
import { CoreManager } from '../../src/desktop/core-manager'
import { JsonLineClient, CoreError } from '../../src/desktop/json-line-client'
const id = 'e40feee8-7aac-403a-8f45-4ae1018109bf'
const roots: string[] = []
afterEach(async () => {
  vi.restoreAllMocks()
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })))
})
it('handles closed, open, suffix, and invalid byte ranges', () => {
  expect(byteRange('bytes=3-8', 20)).toEqual({ start: 3, end: 8 })
  expect(byteRange('bytes=10-', 20)).toEqual({ start: 10, end: 19 })
  expect(byteRange('bytes=-4', 20)).toEqual({ start: 16, end: 19 })
  for (const range of ['bytes=25-', 'bytes=3-1', 'bytes=-0', 'bytes=0-2,4-6', 'bytes=-'])
    expect(byteRange(range, 20)).toBeNull()
})
it('serves only rooted completed meeting WAVs, including Range and missing files', async () => {
  const root = await mkdtemp(join(tmpdir(), 'paa-media-'))
  roots.push(root)
  const audioPath = `meetings/${id}/audio.wav`
  await mkdir(join(root, 'meetings', id), { recursive: true })
  await writeFile(join(root, audioPath), Buffer.alloc(64, 7))
  const core = new CoreManager(process.cwd(), root)
  vi.spyOn(core, 'recordingStatus').mockResolvedValue({
    ok: true,
    value: {
      meetingId: null,
      state: 'idle',
      elapsedMs: 0,
      deviceName: null,
      inputLevel: 0,
      error: null,
    },
  })
  const getter = vi
    .spyOn(core, 'internalMeeting')
    .mockResolvedValue({ id, audioAvailable: true, audioPath, bytes: 20 } as Awaited<
      ReturnType<CoreManager['internalMeeting']>
    >)
  const url = `paa-audio://meeting/${id}`
  const response = await serveMedia(
    new Request(url, { headers: { Range: 'bytes=44-47' } }),
    root,
    core,
  )
  expect(response.status).toBe(206)
  expect(response.headers.get('Content-Range')).toBe('bytes 44-47/64')
  expect((await response.arrayBuffer()).byteLength).toBe(4)
  for (const invalid of [
    'paa-audio://meeting/../../etc/passwd',
    `${url}?path=/etc/passwd`,
    'paa-audio://other/' + id,
  ])
    expect((await serveMedia(new Request(invalid), root, core)).status).toBe(403)
  getter.mockResolvedValue({
    id,
    audioAvailable: true,
    audioPath: '../outside.wav',
    bytes: 20,
  } as Awaited<ReturnType<CoreManager['internalMeeting']>>)
  expect((await serveMedia(new Request(url), root, core)).status).toBe(403)
  getter.mockResolvedValue({ id, audioAvailable: true, audioPath, bytes: 20 } as Awaited<
    ReturnType<CoreManager['internalMeeting']>
  >)
  await rm(join(root, audioPath))
  expect((await serveMedia(new Request(url), root, core)).status).toBe(404)
  if (process.platform !== 'win32') {
    await writeFile(join(root, 'outside.wav'), Buffer.alloc(64))
    await symlink(join(root, 'outside.wav'), join(root, audioPath))
    expect((await serveMedia(new Request(url), root, core)).status).toBe(403)
  }
})
it('recovers a timed-out mutation with one authoritative query and coalesces polling', async () => {
  const root = await mkdtemp(join(tmpdir(), 'paa-timeout-'))
  roots.push(root)
  const core = new CoreManager(process.cwd(), root)
  await core.start()
  const realRequest = JsonLineClient.prototype.request
  const calls: string[] = []
  const spy = vi.spyOn(JsonLineClient.prototype, 'request').mockImplementation(function (
    this: JsonLineClient,
    method,
    timeout,
    params,
  ) {
    calls.push(method)
    if (method === 'recording.start')
      return Promise.reject(new CoreError('timeout', 'test timeout'))
    return realRequest.call(this, method, timeout, params)
  })
  expect((await core.startRecording(id)).ok).toBe(true)
  expect(calls).toEqual(['recording.start', 'recording.status'])
  calls.length = 0
  await Promise.all([core.recordingStatus(), core.recordingStatus(), core.recordingStatus()])
  expect(calls).toEqual(['recording.status'])
  spy.mockRestore()
  await core.stop()
})
