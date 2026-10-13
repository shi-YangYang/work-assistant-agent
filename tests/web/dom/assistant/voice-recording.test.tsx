// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { VoiceRecordButton } from '../../../../apps/web/src/features/assistant/components/composer/controls/VoiceRecordButton'
import { useRecording } from '../../../../apps/web/src/features/assistant/hooks/composer/useRecording'
import { useMessageSubmission } from '../../../../apps/web/src/features/assistant/hooks/composer/useMessageSubmission'
import type { Composer } from '../../../../apps/web/src/features/assistant/lib/audio-capture'
import {
  sendMessage,
  uploadAttachment,
} from '../../../../apps/web/src/features/assistant/api/requests'
import { useWorkspace } from '../../../../apps/web/src/lib/workspace'
import { createVault, deferred, TestWorkspace } from '../helpers'

vi.mock('@web/features/assistant/api/requests', () => ({
  sendMessage: vi.fn(),
  uploadAttachment: vi.fn(),
}))
class Recorder {
  static latest: Recorder
  static isTypeSupported = () => true
  mimeType = 'audio/webm'
  state = 'inactive'
  ondataavailable?: (event: { data: Blob }) => void
  onstop?: () => void
  constructor() {
    Recorder.latest = this
  }
  start() {
    this.state = 'recording'
  }
  stop() {
    this.state = 'inactive'
  }
  finish(data = 'final audio bytes') {
    this.ondataavailable?.({ data: new Blob(data ? [data] : []) })
    this.onstop?.()
  }
}
const stopTrack = vi.fn()
const stream = { getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream
const getUserMedia = vi.fn()
function Harness({ variant = 'icon' }: { variant?: 'icon' | 'bar' }) {
  const { drafts, setDraft } = useWorkspace()
  const composer = (drafts.draft as Composer | undefined) ?? { text: '', key: '', files: [] }
  const [error, setError] = useState<Error | string>('')
  const [limit, setLimit] = useState('')
  const recording = useRecording('draft', setDraft, setError, setLimit)
  const submission = useMessageSubmission({
    composer,
    composerKey: 'draft',
    conversationId: 'chat',
    personaId: 'professional',
    onSent: vi.fn(),
    previewUploading: false,
    capturing: recording.capturing,
    active: recording.active,
    setSendError: setError,
    setLimitError: setLimit,
    retryWait: 0,
    refresh: vi.fn(),
    recordedSend: recording.pendingSend,
  })
  return (
    <>
      <VoiceRecordButton
        variant={variant}
        disabled={submission.busy}
        recording={{
          state: recording.captureState,
          seconds: recording.seconds,
          start: async () => (await recording.capture.current?.start()) ?? false,
          stop: recording.stop,
          cancel: recording.cancel,
        }}
      />
      <button onClick={() => void submission.send()}>发送</button>
      <div aria-label="附件数量">{composer.files.length}</div>
      <div aria-label="错误">{String(error || limit)}</div>
    </>
  )
}
const flush = async (ms = 0) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
function view(variant: 'icon' | 'bar' = 'icon') {
  const vault = createVault()
  vault.writer()('draft', { text: '原来的文字', files: [], key: 'draft' })
  return {
    ...render(
      <TestWorkspace vault={vault}>
        <Harness variant={variant} />
      </TestWorkspace>,
    ),
    vault,
  }
}
const mic = () => screen.getByRole('button', { name: '录制语音' })
const pointer = { pointerId: 1, isPrimary: true, button: 0, clientX: 100, clientY: 200 }
async function hold(button = mic()) {
  fireEvent.pointerDown(button, pointer)
  await flush(350)
  return button
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  getUserMedia.mockResolvedValue(stream)
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal(
    'PointerEvent',
    class extends MouseEvent {
      pointerId: number
      isPrimary: boolean
      constructor(type: string, options: PointerEventInit = {}) {
        super(type, options)
        this.pointerId = options.pointerId ?? 1
        this.isPrimary = options.isPrimary ?? true
      }
    },
  )
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  vi.stubGlobal(
    'URL',
    Object.assign(URL, {
      createObjectURL: vi.fn(() => 'blob:recording'),
      revokeObjectURL: vi.fn(),
    }),
  )
  vi.mocked(uploadAttachment).mockResolvedValue({ id: 'voice', kind: 'audio' } as never)
  vi.mocked(sendMessage).mockResolvedValue({
    conversationId: 'chat',
    messageId: 'message',
    jobId: 'job',
  })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
it('keeps short presses as record, stop and manual send', async () => {
  view()
  const button = mic()
  fireEvent.pointerDown(button, pointer)
  await flush(100)
  fireEvent.pointerUp(button, pointer)
  fireEvent.click(button, { detail: 1 })
  await flush()
  expect(getUserMedia).toHaveBeenCalledOnce()
  expect(screen.queryByRole('status')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '停止录音 · 0 秒' }))
  act(() => Recorder.latest.finish())
  await flush()
  expect(screen.getByLabelText('附件数量').textContent).toBe('1')
  expect(sendMessage).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await flush()
  expect(sendMessage).toHaveBeenCalledOnce()
})
it.each(['icon', 'bar'] as const)(
  'sends once from the %s control after release and the final audio event, preserving the current draft',
  async (variant) => {
    view(variant)
    const button = await hold(
      screen.getByRole('button', { name: variant === 'bar' ? '点击录音，长按发送' : '录制语音' }),
    )
    expect(screen.getByRole('status').textContent).toContain('松开发送，上滑取消')
    fireEvent.pointerUp(button, pointer)
    fireEvent.click(button, { detail: 1 })
    expect(uploadAttachment).not.toHaveBeenCalled()
    act(() => Recorder.latest.finish())
    await flush()
    act(() => Recorder.latest.finish())
    await flush()
    expect(getUserMedia).toHaveBeenCalledOnce()
    expect(uploadAttachment).toHaveBeenCalledOnce()
    expect(sendMessage).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({
        text: '原来的文字',
        attachmentIds: ['voice'],
        voiceCommandAttachmentIds: ['voice'],
      }),
      expect.any(String),
    )
    expect(screen.queryByRole('status')).toBeNull()
  },
)
it.each(['slide', 'pointercancel', 'lostpointercapture'])(
  'discards a held recording on %s without sending',
  async (reason) => {
    view('bar')
    const button = screen.getByRole('button', { name: '点击录音，长按发送' })
    act(() => button.focus())
    expect(document.activeElement).toBe(button)
    await hold(button)
    if (reason === 'slide') {
      fireEvent.pointerMove(button, { ...pointer, clientY: 100 })
      expect(screen.getByRole('status').textContent).toContain('松开取消')
      fireEvent.pointerUp(button, { ...pointer, clientY: 100 })
    } else if (reason === 'pointercancel') fireEvent.pointerCancel(button, pointer)
    else fireEvent.lostPointerCapture(button, pointer)
    fireEvent.click(button, { detail: 1 })
    act(() => Recorder.latest.finish())
    await flush()
    expect(document.activeElement).not.toBe(button)
    expect(getUserMedia).toHaveBeenCalledOnce()
    expect(stopTrack).toHaveBeenCalled()
    expect(screen.getByLabelText('附件数量').textContent).toBe('0')
    expect(uploadAttachment).not.toHaveBeenCalled()
    expect(sendMessage).not.toHaveBeenCalled()
  },
)
it('cancels pending permission on release and stops a stream granted later', async () => {
  const permission = deferred<MediaStream>()
  getUserMedia.mockReturnValue(permission.promise)
  view()
  const button = await hold()
  expect(screen.getByRole('status').textContent).toContain('正在申请麦克风')
  fireEvent.pointerUp(button, pointer)
  fireEvent.click(button, { detail: 1 })
  await act(async () => permission.resolve(stream))
  await flush()
  expect(stopTrack).toHaveBeenCalled()
  expect(sendMessage).not.toHaveBeenCalled()
  expect(getUserMedia).toHaveBeenCalledOnce()
  expect(mic()).toBeTruthy()
})
it('clears the hold indicator after permission failure', async () => {
  getUserMedia.mockRejectedValue(Object.assign(new Error('denied'), { name: 'NotAllowedError' }))
  view()
  const button = await hold()
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.getByLabelText('错误').textContent).toContain('权限未获允许')
  fireEvent.pointerUp(button, pointer)
  fireEvent.click(button, { detail: 1 })
  expect(getUserMedia).toHaveBeenCalledOnce()
  expect(sendMessage).not.toHaveBeenCalled()
})
it('never auto sends final data arriving after navigation', async () => {
  const { unmount, vault } = view()
  const button = await hold()
  fireEvent.pointerUp(button, pointer)
  unmount()
  Recorder.latest.finish()
  await flush()
  expect((vault.getSnapshot().draft as Composer).files).toHaveLength(1)
  expect(sendMessage).not.toHaveBeenCalled()
})
it('does not send existing draft text when the recording yields no file', async () => {
  view()
  const button = await hold()
  fireEvent.pointerUp(button, pointer)
  act(() => Recorder.latest.finish(''))
  await flush()
  expect(sendMessage).not.toHaveBeenCalled()
})
it('retains audio after an upload failure and waits for manual retry', async () => {
  vi.mocked(uploadAttachment).mockRejectedValue(new Error('网络中断'))
  view()
  const button = await hold()
  fireEvent.pointerUp(button, pointer)
  act(() => Recorder.latest.finish())
  await flush()
  expect(screen.getByLabelText('附件数量').textContent).toBe('1')
  expect(screen.getByLabelText('错误').textContent).toContain('网络中断')
  await flush(5000)
  expect(uploadAttachment).toHaveBeenCalledOnce()
  expect(sendMessage).not.toHaveBeenCalled()
})
