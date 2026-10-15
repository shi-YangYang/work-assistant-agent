// @vitest-environment jsdom
import type { Attachment, WorkMessage } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { StrictMode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AudioPlayer } from '../../../../apps/web/src/components/media/AudioPlayer'
import { MessageVoice } from '../../../../apps/web/src/features/assistant/components/messages/MessageVoice'
import { MessageCard } from '../../../../apps/web/src/features/assistant/components/messages/MessageCard'
import { correctTranscript } from '../../../../apps/web/src/features/assistant/api/requests'
import { ApiError } from '../../../../apps/web/src/api/client'
import { createVault, deferred, dialogs, TestWorkspace } from '../helpers'

vi.mock('../../../../apps/web/src/features/assistant/api/requests', async (original) => ({
  ...(await original<typeof import('../../../../apps/web/src/features/assistant/api/requests')>()),
  correctTranscript: vi.fn(),
}))

const attachment = (id = 'audio', changes: Partial<Attachment> = {}): Attachment => ({
  id,
  kind: 'audio',
  name: `${id}.wav`,
  mime: 'audio/wav',
  size: 1200,
  duration: 26,
  url: `/media/${id}`,
  previewUrl: `/preview/${id}`,
  ...changes,
})
const message = (changes: Partial<WorkMessage> = {}): WorkMessage => ({
  id: 'message',
  conversationId: 'conversation',
  ownerId: 'owner',
  text: '',
  reply: '',
  replyTo: null,
  transcript: '今天完成了方案设计。',
  transcriptRevision: 2,
  createdAt: '2026-10-15T08:00:00Z',
  attachments: [attachment()],
  drafts: [],
  suggestions: [],
  job: null,
  ...changes,
})
const audio = (container: HTMLElement) => container.querySelector('audio')!
function metadata(element: HTMLAudioElement, duration: number, seekable = true) {
  Object.defineProperties(element, {
    duration: { configurable: true, value: duration },
    seekable: {
      configurable: true,
      value: { length: seekable ? 1 : 0, start: () => 0, end: () => duration },
    },
  })
  fireEvent.loadedMetadata(element)
}
function pauseState(element: HTMLMediaElement, paused: boolean) {
  Object.defineProperty(element, 'paused', { configurable: true, value: paused })
}
async function clickPlay(name = '播放voice.wav') {
  await act(async () => fireEvent.click(screen.getByRole('button', { name })))
}
beforeEach(() => {
  dialogs()
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function () {
    pauseState(this, false)
    this.dispatchEvent(new Event('play'))
    this.dispatchEvent(new Event('playing'))
    return Promise.resolve()
  })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function () {
    if (this.paused) return
    pauseState(this, true)
    this.dispatchEvent(new Event('pause'))
  })
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.mocked(correctTranscript).mockReset()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

it('loads only on playback and supports actual duration, pause, seek and replay', async () => {
  const frames = new Map<number, FrameRequestCallback>()
  let frameId = 0
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    frames.set(++frameId, callback)
    return frameId
  })
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation((id) => {
    frames.delete(id)
  })
  const view = render(<AudioPlayer src="/voice" name="voice.wav" duration={26} />)
  const element = audio(view.container)
  expect(element.preload).toBe('none')
  expect(element.controls).toBe(false)
  expect(HTMLMediaElement.prototype.load).not.toHaveBeenCalled()
  expect(screen.getByText('0:00 / 0:26')).toBeTruthy()
  expect((screen.getByRole('slider') as HTMLInputElement).disabled).toBe(true)
  await clickPlay()
  metadata(element, 30)
  // The cursor follows playback between sparse native timeupdate events.
  element.currentTime = 0.016
  act(() => {
    const pending = [...frames.values()]
    frames.clear()
    pending.forEach((callback) => callback(16))
  })
  expect((screen.getByRole('slider') as HTMLInputElement).valueAsNumber).toBe(0.016)
  expect(frames.size).toBe(1)
  fireEvent.waiting(element)
  expect(frames.size).toBe(0)
  fireEvent.playing(element)
  expect(frames.size).toBe(1)
  fireEvent.change(screen.getByRole('slider'), { target: { value: '12.5' } })
  expect(element.currentTime).toBe(12.5)
  expect(screen.getByText('0:12 / 0:30')).toBeTruthy()
  await clickPlay('暂停voice.wav')
  expect(element.paused).toBe(true)
  expect(frames.size).toBe(0)
  await clickPlay()
  Object.defineProperty(element, 'ended', { configurable: true, value: true })
  fireEvent.ended(element)
  expect(frames.size).toBe(0)
  await clickPlay()
  expect(element.currentTime).toBe(0)
  view.unmount()
  expect(frames.size).toBe(0)
})

it('retains its source after StrictMode effect cleanup and setup', async () => {
  const view = render(
    <StrictMode>
      <AudioPlayer src="/voice" name="voice.wav" />
    </StrictMode>,
  )
  expect(audio(view.container).getAttribute('src')).toBe('/voice')
  await clickPlay()
  expect(audio(view.container).paused).toBe(false)
})

it('keeps unknown or unseekable audio playable without invalid duration or progress', async () => {
  const view = render(<AudioPlayer src="/voice" name="voice.wav" duration={Infinity} />)
  const element = audio(view.container)
  expect(screen.getByText('0:00 / --:--')).toBeTruthy()
  metadata(element, NaN, false)
  await clickPlay()
  element.currentTime = 3
  fireEvent.timeUpdate(element)
  expect(screen.getByText('0:03 / --:--')).toBeTruthy()
  expect((screen.getByRole('slider') as HTMLInputElement).disabled).toBe(true)
  metadata(element, 30, false)
  expect((screen.getByRole('slider') as HTMLInputElement).disabled).toBe(true)
})

it('reflects buffering and external pause events', async () => {
  const view = render(<AudioPlayer src="/voice" name="voice.wav" />)
  const element = audio(view.container)
  await clickPlay()
  fireEvent.waiting(element)
  expect(screen.getByRole('button', { name: '暂停voice.wav' }).getAttribute('aria-busy')).toBe(
    'true',
  )
  fireEvent.playing(element)
  expect(screen.getByRole('button', { name: '暂停voice.wav' }).getAttribute('aria-busy')).toBe(
    'false',
  )
  act(() => element.pause())
  await clickPlay()
  expect(element.paused).toBe(false)
})

it('shows one short failure and retries only after another explicit play', async () => {
  vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new Error('not allowed'))
  const view = render(<AudioPlayer src="/voice" name="voice.wav" />)
  await clickPlay()
  expect(screen.getByRole('status').textContent).toContain('暂时无法播放')
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
  await clickPlay()
  expect(screen.queryByRole('status')).toBeNull()
  const element = audio(view.container)
  Object.defineProperty(element, 'error', { configurable: true, value: { code: 3 } })
  fireEvent.error(element)
  expect(screen.getByRole('status').textContent).toContain('暂时无法播放')
  await clickPlay()
  expect(HTMLMediaElement.prototype.load).toHaveBeenCalledTimes(1)
})

it('pauses the prior player and rejects a late play event after rapidly switching', async () => {
  const pending = deferred<void>()
  vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(() => pending.promise)
  const view = render(
    <>
      <AudioPlayer src="/one" name="one" />
      <AudioPlayer src="/two" name="two" />
    </>,
  )
  await clickPlay('播放one')
  await clickPlay('播放two')
  const [one, two] = view.container.querySelectorAll('audio')
  await act(async () => {
    pauseState(one, false)
    one.dispatchEvent(new Event('play'))
    pending.resolve()
  })
  expect(one.paused).toBe(true)
  expect(two.paused).toBe(false)
  expect(screen.getByRole('button', { name: '播放one' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '暂停two' })).toBeTruthy()
})

it('ignores stale playback rejections and releases audio on source change and unmount', async () => {
  const pending = deferred<void>()
  vi.mocked(HTMLMediaElement.prototype.play).mockImplementationOnce(() => pending.promise)
  const view = render(<AudioPlayer src="/old" name="voice.wav" />)
  const old = audio(view.container)
  await clickPlay()
  view.rerender(<AudioPlayer src="/new" name="voice.wav" />)
  expect(old.getAttribute('src')).toBeNull()
  expect(audio(view.container)).not.toBe(old)
  await act(async () => pending.reject(new Error('aborted')))
  expect(screen.queryByRole('status')).toBeNull()
  await clickPlay()
  const current = audio(view.container)
  view.unmount()
  expect(current.paused).toBe(true)
  expect(current.getAttribute('src')).toBeNull()
})

it('keeps the audio node and playback stable while opening and refreshing the transcript', async () => {
  const initial = message()
  const view = render(<MessageVoice message={initial} own onChange={vi.fn()} />)
  const element = audio(view.container)
  expect(element.getAttribute('src')).toBe('/preview/audio')
  expect(screen.getByRole('button', { name: '转文字' }).getAttribute('aria-expanded')).toBe('false')
  await clickPlay('播放audio.wav')
  fireEvent.click(screen.getByRole('button', { name: '转文字' }))
  view.rerender(
    <MessageVoice
      message={{
        ...initial,
        attachments: [{ ...initial.attachments[0] }],
        transcript: '更新后的文字',
        transcriptRevision: 3,
      }}
      own
      onChange={vi.fn()}
    />,
  )
  expect(audio(view.container)).toBe(element)
  expect(element.paused).toBe(false)
  expect(screen.getByText('更新后的文字')).toBeTruthy()
  expect(screen.getByRole('button', { name: '转文字' }).getAttribute('aria-expanded')).toBe('true')
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
})

it('groups multiple audio files under one transcript and pauses for editing', async () => {
  const changed = vi.fn()
  render(
    <MessageVoice
      message={message({ attachments: [attachment('one'), attachment('two')] })}
      own
      onChange={changed}
    />,
  )
  expect(screen.getAllByRole('button', { name: '转文字' })).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: '改文字' })).toHaveLength(1)
  await clickPlay('播放语音 2')
  fireEvent.click(screen.getByRole('button', { name: '改文字' }))
  const editor = screen.getByRole('dialog', { name: '修正语音文字' })
  expect(screen.getByRole('button', { name: '播放语音 2' })).toBeTruthy()
  expect(
    (within(editor).getByRole('textbox', { name: '语音文字' }) as HTMLTextAreaElement).maxLength,
  ).toBe(8000)
  fireEvent.change(within(editor).getByRole('textbox', { name: '语音文字' }), {
    target: { value: '修正后的内容' },
  })
  fireEvent.click(within(editor).getByRole('button', { name: '保存修正' }))
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
  expect(correctTranscript).toHaveBeenCalledWith(expect.objectContaining({ id: 'message' }), {
    text: '修正后的内容',
    expectedRevision: 2,
  })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
})

it('retains edited text after a conflict and permits clearing the transcript', async () => {
  vi.mocked(correctTranscript).mockRejectedValueOnce(
    new ApiError(409, 'revision_conflict', '转写已被更新，请读取最新内容'),
  )
  const changed = vi.fn()
  render(<MessageVoice message={message()} own onChange={changed} />)
  fireEvent.click(screen.getByRole('button', { name: '改文字' }))
  const editor = screen.getByRole('dialog', { name: '修正语音文字' })
  const textbox = within(editor).getByRole('textbox', { name: '语音文字' }) as HTMLTextAreaElement
  fireEvent.change(textbox, { target: { value: '保留我正在修改的文字' } })
  fireEvent.click(within(editor).getByRole('button', { name: '保存修正' }))
  await within(editor).findByText(/转写已被更新/)
  expect(textbox.value).toBe('保留我正在修改的文字')
  expect(changed).not.toHaveBeenCalled()
  fireEvent.change(textbox, { target: { value: '' } })
  fireEvent.click(within(editor).getByRole('button', { name: '保存修正' }))
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
  expect(correctTranscript).toHaveBeenLastCalledWith(expect.anything(), {
    text: '',
    expectedRevision: 2,
  })
})

it('keeps recognition status distinct from playback errors and hides editing for other users', async () => {
  const view = render(
    <MessageVoice message={message({ transcript: '' })} own={false} onChange={vi.fn()} />,
  )
  expect(screen.queryByRole('button', { name: '改文字' })).toBeNull()
  fireEvent.error(audio(view.container))
  expect(screen.getByText('待识别')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '转文字 待识别' }))
  expect(screen.getByText('等待识别')).toBeTruthy()
  expect(screen.getByRole('status').textContent).toContain('暂时无法播放')
})

it('preserves historical transcripts without rendering an empty player', () => {
  const view = render(
    <MessageVoice message={message({ attachments: [] })} own onChange={vi.fn()} />,
  )
  expect(view.container.querySelector('audio')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '转文字' }))
  expect(screen.getByText('今天完成了方案设计。')).toBeTruthy()
  expect(screen.getByRole('button', { name: '改文字' })).toBeTruthy()
})

it('integrates one voice card alongside the original text, images and documents', () => {
  const item = message({
    text: '请看看这些材料',
    attachments: [
      attachment(),
      attachment('picture', { kind: 'image', name: 'photo.png', mime: 'image/png' }),
      attachment('notes', { kind: 'document', name: 'notes.txt', mime: 'text/plain' }),
    ],
  })
  const view = render(
    <MemoryRouter>
      <TestWorkspace vault={createVault()}>
        <MessageCard message={item} own onChange={vi.fn()} />
      </TestWorkspace>
    </MemoryRouter>,
  )
  expect(screen.getByText('请看看这些材料')).toBeTruthy()
  expect(screen.getByRole('button', { name: '预览photo.png' })).toBeTruthy()
  expect(screen.getByText('notes.txt')).toBeTruthy()
  expect(screen.getAllByRole('region', { name: '语音消息' })).toHaveLength(1)
  expect(view.container.querySelectorAll('audio')).toHaveLength(1)
})
