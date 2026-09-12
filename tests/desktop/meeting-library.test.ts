import { mkdtemp, readFile, readdir, rm, writeFile, mkdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
import { CoreManager } from '../../src/desktop/core-manager'
import { DesktopLibrary, safeFilename, writeSnapshot } from '../../src/desktop/meeting-library'
import { MediaAccess, serveMedia } from '../../src/desktop/media'
import {
  highlightedParts,
  meetingQuery,
  QueryGeneration,
} from '../../src/renderer/meeting-library-query'
const id = 'e40feee8-7aac-403a-8f45-4ae1018109bf'
const roots: string[] = []
afterEach(async () => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })))
})
it('preserves literal highlights, local day boundaries and rejects stale query generations', () => {
  expect(highlightedParts('<img> 汉 CPU %_', 'cpu')).toEqual([
    { text: '<img> 汉 ', hit: false },
    { text: 'CPU', hit: true },
    { text: ' %_', hit: false },
  ])
  expect(highlightedParts('a%_b%_', '%_').filter((part) => part.hit)).toHaveLength(2)
  const query = meetingQuery(' 汉 ', '2026-09-12', '2026-09-12')
  expect(new Date(query.from!).getDate()).toBe(12)
  expect(new Date(query.from!).getHours()).toBe(0)
  expect(new Date(query.to!).getDate()).toBe(13)
  expect(() => meetingQuery('', '2026-09-13', '2026-09-12')).toThrow()
  expect(() => meetingQuery('', '2026-02-30', '')).toThrow()
  const requests = new QueryGeneration()
  const old = requests.next()
  const current = requests.next()
  expect(requests.current(old)).toBe(false)
  expect(requests.current(current)).toBe(true)
})
it('keeps pagination bound to applied results through debounce, stale pages and IME input', async () => {
  vi.useFakeTimers()
  const requests = new QueryGeneration()
  const oldQuery = meetingQuery('旧条件', '', '')
  requests.apply(requests.next(), oldQuery)
  const latePage = requests.page(25)!
  expect(latePage.query).toEqual({ ...oldQuery, offset: 25 })
  expect(requests.page(25)).toBeNull()

  const replacement = meetingQuery('新条件', '2026-09-12', '')
  const version = requests.next()
  let firstPageAccepted = false
  setTimeout(() => {
    firstPageAccepted = requests.apply(version, replacement)
  }, 250)
  expect(requests.page(25)).toBeNull()
  await vi.advanceTimersByTimeAsync(249)
  expect(requests.page(25)).toBeNull()
  expect(requests.apply(latePage.version, latePage.query)).toBe(false)
  requests.finish(latePage.version)
  await vi.advanceTimersByTimeAsync(1)
  expect(firstPageAccepted).toBe(true)
  const newPage = requests.page(25)!
  expect(newPage.query).toEqual({ ...replacement, offset: 25 })

  // Composition invalidates a page already in flight, even before its text changes.
  requests.next()
  expect(requests.page(25)).toBeNull()
  expect(requests.apply(newPage.version, newPage.query)).toBe(false)
  requests.finish(newPage.version)
  requests.next()
  expect(requests.page(25)).toBeNull()
  const committed = meetingQuery('中文已提交', '', '')
  expect(requests.apply(requests.next(), committed)).toBe(true)
  expect(requests.page(25)?.query).toEqual({ ...committed, offset: 25 })

  // Clearing filters also waits for its own first page before any further paging.
  const clearedVersion = requests.next()
  expect(requests.page(25)).toBeNull()
  expect(requests.apply(clearedVersion, meetingQuery('', '', ''))).toBe(true)
  expect(requests.page(25)?.query).toEqual(meetingQuery('', '', '', 25))
})
it('sanitizes portable filenames without interpreting user text as a path', () => {
  expect(safeFilename('../../CON:notes?', '2026-09-12', 'md')).toBe(
    '.._.._CON_notes_-2026-09-12.md',
  )
  expect(safeFilename('CON', '2026-09-12', 'txt')).toBe('_CON-2026-09-12.txt')
  expect(safeFilename('中文项目', '2026-09-12', 'md')).toContain('中文项目')
})
it('writes complete multibyte chunks atomically and preserves target on read failure', async () => {
  const root = await mkdtemp(join(tmpdir(), 'paa-export-'))
  roots.push(root)
  const core = new CoreManager(process.cwd(), root)
  const text = Buffer.from('中文📚\n'.repeat(2000))
  const request = vi.spyOn(core, 'libraryRequest').mockImplementation(async (method, params) => {
    if (method !== 'library.read') throw new Error('Unexpected call')
    const offset = params.offset as number,
      next = Math.min(text.length, offset + 16384)
    return {
      ok: true,
      value: {
        data: text.subarray(offset, next).toString('base64'),
        nextOffset: next,
        done: next === text.length,
      },
    } as never
  })
  const target = join(root, '原文.txt')
  await writeFile(target, 'original')
  await writeSnapshot(core, id, target, text.length)
  expect(await readFile(target)).toEqual(text)
  await writeFile(target, 'original')
  request.mockResolvedValueOnce({ ok: false, message: 'controlled disk/read failure' })
  await expect(writeSnapshot(core, id, target, text.length)).rejects.toThrow('controlled')
  expect(await readFile(target, 'utf8')).toBe('original')
  expect(await readdir(root)).toEqual(['原文.txt'])
})
it('canceling native save releases the snapshot and clipboard failures never report success', async () => {
  const core = new CoreManager('', '')
  const request = vi.spyOn(core, 'libraryRequest').mockImplementation(async (method) => {
    const value =
      method === 'library.start'
        ? { id }
        : method === 'library.status'
          ? { state: 'completed', value: { bytes: 3, title: '会议', date: '2026-09-12' } }
          : method === 'library.read'
            ? { data: Buffer.from('abc').toString('base64'), nextOffset: 3, done: true }
            : { released: true }
    return { ok: true, value } as never
  })
  const save = vi.fn(async () => null),
    copy = vi.fn(() => {
      throw new Error('clipboard denied')
    })
  const library = new DesktopLibrary(core, { save, copy })
  expect(
    await library.execute('export', {
      meetingId: id,
      format: 'md',
      scope: 'summary',
      timestamps: true,
    }),
  ).toEqual({ ok: true, value: { canceled: true } })
  expect(request.mock.calls.filter(([method]) => method === 'library.read')).toHaveLength(0)
  expect(request.mock.lastCall).toEqual(['library.release', { id }])
  expect(await library.execute('copy', { meetingId: id })).toEqual({
    ok: false,
    message: 'clipboard denied',
  })
  expect(request.mock.lastCall).toEqual(['library.release', { id }])
  expect((await library.execute('delete', { meetingId: '../outside' })).ok).toBe(false)
  expect((await library.execute('export', { meetingId: id, path: '/outside' })).ok).toBe(false)
})
it('deletion blocks in-flight and new media reads and waits for actual stream closure', async () => {
  const root = await mkdtemp(join(tmpdir(), 'paa-media-release-'))
  roots.push(root)
  const audioPath = `meetings/${id}/audio.wav`
  await mkdir(join(root, 'meetings', id), { recursive: true })
  await writeFile(join(root, audioPath), Buffer.alloc(200000))
  const core = new CoreManager(process.cwd(), root)
  vi.spyOn(core, 'recordingStatus').mockResolvedValue({
    ok: true,
    value: { state: 'idle' },
  } as never)
  let proceed!: () => void
  const pending = new Promise<void>((resolve) => {
    proceed = resolve
  })
  vi.spyOn(core, 'internalMeeting').mockImplementation(async () => {
    await pending
    return { id, audioAvailable: true, audioPath, bytes: 200000 - 44 } as never
  })
  const access = new MediaAccess(),
    url = `paa-audio://meeting/${id}`
  const response = serveMedia(new Request(url), root, core, access)
  const releasing = access.block(id)
  expect((await serveMedia(new Request(url), root, core, access)).status).toBe(409)
  proceed()
  const body = await response
  expect(body.status).toBe(200)
  await releasing
  await rm(join(root, audioPath))
  expect(await readdir(join(root, 'meetings', id))).toEqual([])
})

it('uses the real core JSON Lines lifecycle for background search and validation', async () => {
  const root = await mkdtemp(join(tmpdir(), 'paa-library-protocol-'))
  roots.push(root)
  const core = new CoreManager(process.cwd(), root)
  try {
    expect((await core.start()).connection).toBe('ready')
    const library = new DesktopLibrary(core, { save: async () => null, copy: () => {} })
    expect(await library.execute('rename', { meetingId: id, title: '' })).toMatchObject({
      ok: false,
      code: 'invalid_title',
      message: '名称须为 1～100 个字符，不能包含换行或控制字符。',
    })
    expect(
      await library.execute('search', { text: '中文%_', from: null, to: null, offset: 0 }),
    ).toEqual({ ok: true, value: { items: [], hasMore: false } })
    expect(
      (await library.execute('search', { text: 'x'.repeat(201), from: null, to: null, offset: 0 }))
        .ok,
    ).toBe(false)
  } finally {
    await core.stop()
  }
})
