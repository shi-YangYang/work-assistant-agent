import { useAttachmentUploads } from '../../../../apps/web/src/features/assistant/hooks/composer/useAttachmentUploads'
// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useCallback, useState, type ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { VoiceRecordButton } from '../../../../apps/web/src/features/assistant/components/composer/controls/VoiceRecordButton'
import { ComposerAttachments } from '../../../../apps/web/src/features/assistant/components/composer/attachments/ComposerAttachments'
import { recordingPreview } from '../../../../apps/web/src/features/assistant/lib/audio-preview'
import { useRecording } from '../../../../apps/web/src/features/assistant/hooks/composer/useRecording'
import { useMessageSubmission } from '../../../../apps/web/src/features/assistant/hooks/composer/useMessageSubmission'
import type { Composer } from '../../../../apps/web/src/features/assistant/lib/audio-capture'
import {
  sendMessage,
  uploadAttachment,
} from '../../../../apps/web/src/features/assistant/api/requests'
import { Workspace, useWorkspace } from '../../../../apps/web/src/lib/workspace'
import { createVault, deferred, TestWorkspace } from '../helpers'

vi.mock('@web/features/assistant/api/requests', () => ({
  sendMessage: vi.fn(),
  uploadAttachment: vi.fn(),
}))
vi.mock('@web/api/attachments', async () => {
  const requests = await import('@web/features/assistant/api/requests')
  return {
    uploadAttachment: requests.uploadAttachment,
    deleteDraftAttachment: vi.fn(async () => ({ ok: true })),
  }
})
vi.mock('@web/features/assistant/lib/audio-preview', () => ({
  recordingPreview: vi.fn(async (file: File) => file),
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
const notify = vi.fn()
function Notifications({ children }: { children: ReactNode }) {
  const workspace = useWorkspace()
  return <Workspace value={{ ...workspace, notify }}>{children}</Workspace>
}
function Harness({
  variant = 'icon',
  retryWait = 0,
  newConversation = false,
}: {
  variant?: 'icon' | 'bar'
  retryWait?: number
  newConversation?: boolean
}) {
  const { drafts, setDraft } = useWorkspace()
  const composer = (drafts.draft as Composer | undefined) ?? { text: '', key: '', files: [] }
  const uploadWriter = useCallback(
    (_key: string, value: unknown) => setDraft('draft', value),
    [setDraft],
  )
  useAttachmentUploads('voice-test', { 'composer:first': composer }, uploadWriter)
  const [error, setError] = useState<Error | string>('')
  const [limit, setLimit] = useState('')
  const recording = useRecording('draft', setDraft, setError, setLimit)
  const submission = useMessageSubmission({
    composer,
    composerKey: 'draft',
    conversationId: newConversation ? undefined : 'chat',
    personaId: 'professional',
    onSent: vi.fn(),
    previewUploading: false,
    capturing: recording.capturing,
    active: recording.active,
    setSendError: setError,
    setLimitError: setLimit,
    retryWait,
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
      <ComposerAttachments
        composer={composer}
        directSendingFile={submission.directSendingFile}
        locked={submission.busy}
        setGallery={vi.fn()}
        previewImages={[]}
        setPdf={vi.fn()}
        change={(next) => setDraft('draft', next)}
      />
      <button disabled={submission.busy} onClick={() => void submission.send()}>
        发送
      </button>
      <div aria-label="发送状态">{submission.busy ? '正在发送' : '空闲'}</div>
      <div aria-label="附件数量">{composer.files.length}</div>
      <div aria-label="错误">{String(error || limit)}</div>
    </>
  )
}
const flush = async (ms = 0) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
function view(variant: 'icon' | 'bar' = 'icon', retryWait = 0, newConversation = false) {
  const vault = createVault()
  vault.writer()('draft', { text: '原来的文字', files: [], key: 'draft' })
  return {
    ...render(
      <TestWorkspace vault={vault}>
        <Notifications>
          <Harness variant={variant} retryWait={retryWait} newConversation={newConversation} />
        </Notifications>
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
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
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
  vi.restoreAllMocks()
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
  expect(screen.getByRole('button', { name: '播放语音 1' })).toBeTruthy()
  expect(sendMessage).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await flush()
  expect(sendMessage).toHaveBeenCalledOnce()
  expect(sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({ text: '原来的文字' }),
    expect.any(String),
  )
})
it.each(['icon', 'bar'] as const)(
  'sends once from the %s control after release and the final audio event, preserving the current draft',
  async (variant) => {
    const { vault } = view(variant)
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
        text: '',
        attachmentIds: ['voice'],
        voiceCommandAttachmentIds: ['voice'],
      }),
      expect.any(String),
    )
    expect(screen.queryByRole('status')).toBeNull()
    expect(recordingPreview).not.toHaveBeenCalled()
    expect(vault.getSnapshot().draft).toMatchObject({
      text: '原来的文字',
      files: [],
      sending: false,
    })
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
it('keeps cancellation stable near the threshold and allows moving back to continue', async () => {
  view('bar')
  const button = await hold(screen.getByRole('button', { name: '点击录音，长按发送' }))
  const move = (distance: number) =>
    fireEvent.pointerMove(button, { ...pointer, clientY: pointer.clientY - distance })
  move(59)
  expect(screen.getByRole('status').textContent).toContain('松开发送，上滑取消')
  move(60)
  expect(screen.getByRole('status').textContent).toContain('松开取消')
  move(55)
  expect(screen.getByRole('status').textContent).toContain('松开取消')
  move(39)
  expect(screen.getByRole('status').textContent).toContain('松开发送，上滑取消')
  fireEvent.pointerUp(button, pointer)
  act(() => Recorder.latest.finish())
  await flush()
  expect(sendMessage).toHaveBeenCalledOnce()
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
it.each(['upload', 'message'] as const)(
  'discards held audio after %s failure and only shows a notice',
  async (phase) => {
    vi.mocked(phase === 'upload' ? uploadAttachment : sendMessage).mockRejectedValue(
      new Error('网络中断'),
    )
    const { vault } = view()
    const existing = {
      id: 'existing',
      file: new File(['notes'], 'notes.txt', { type: 'text/plain' }),
      url: 'blob:existing',
      attachment: { id: 'existing', kind: 'document' },
    }
    act(() => vault.writer()('draft', { text: '原来的文字', key: 'draft', files: [existing] }))
    const button = await hold()
    fireEvent.pointerUp(button, pointer)
    act(() => Recorder.latest.finish())
    await flush()
    expect(screen.getByLabelText('附件数量').textContent).toBe('1')
    expect(screen.queryByRole('button', { name: '播放语音 1' })).toBeNull()
    expect(screen.getByLabelText('错误').textContent).toBe('')
    expect(notify).toHaveBeenCalledExactlyOnceWith('语音发送未完成')
    expect(recordingPreview).not.toHaveBeenCalled()
    expect(vault.getSnapshot().draft).toMatchObject({
      text: '原来的文字',
      files: [existing],
      sending: false,
    })
    expect((vault.getSnapshot().draft as Composer).pending).toBeUndefined()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:recording')
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:existing')
    await flush(5000)
    expect(uploadAttachment).toHaveBeenCalledOnce()
    expect(sendMessage).toHaveBeenCalledTimes(phase === 'upload' ? 0 : 1)
  },
)
it('sends a held recording without mounting a draft preview during upload or message acceptance', async () => {
  const upload = deferred<Awaited<ReturnType<typeof uploadAttachment>>>()
  const accepted = deferred<Awaited<ReturnType<typeof sendMessage>>>()
  const notesUpload = deferred<Awaited<ReturnType<typeof uploadAttachment>>>()
  vi.mocked(uploadAttachment).mockImplementation((options) =>
    (options.body as FormData).get('file') instanceof File &&
    ((options.body as FormData).get('file') as File).name === 'notes.txt'
      ? notesUpload.promise
      : upload.promise,
  )
  vi.mocked(sendMessage).mockReturnValue(accepted.promise)
  const { vault } = view('bar')
  const existing = {
    id: 'existing',
    file: new File(['notes'], 'notes.txt', { type: 'text/plain' }),
    url: 'blob:existing',
  }
  const original = {
    text: '原来的文字',
    key: 'draft',
    files: [existing],
    replyTo: 'previous-message',
    workReference: { workId: 'work' },
  }
  act(() => vault.writer()('draft', original))
  const button = await hold(screen.getByRole('button', { name: '点击录音，长按发送' }))
  fireEvent.pointerUp(button, pointer)
  act(() => Recorder.latest.finish())
  await flush()
  expect(screen.getByLabelText('发送状态').textContent).toBe('正在发送')
  expect(screen.getByRole('region', { name: '待发送附件，共 1 个，可横向滚动' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '播放语音 1' })).toBeNull()
  expect(recordingPreview).not.toHaveBeenCalled()
  await act(async () => upload.resolve({ id: 'voice', kind: 'audio' } as never))
  await flush()
  expect(sendMessage).toHaveBeenCalledOnce()
  expect(uploadAttachment).toHaveBeenCalledTimes(2)
  expect((vi.mocked(uploadAttachment).mock.calls[1][0].body as FormData).get('file')).not.toBe(
    existing.file,
  )
  expect(vi.mocked(sendMessage).mock.calls[0][0]).toMatchObject({
    text: '',
    attachmentIds: ['voice'],
    voiceCommandAttachmentIds: ['voice'],
    replyTo: null,
  })
  expect(vi.mocked(sendMessage).mock.calls[0][0].workReference).toBeUndefined()
  expect(screen.getByRole('region', { name: '待发送附件，共 1 个，可横向滚动' })).toBeTruthy()
  expect(recordingPreview).not.toHaveBeenCalled()
  await act(async () =>
    accepted.resolve({ conversationId: 'chat', messageId: 'message', jobId: 'job' }),
  )
  await flush()
  expect(screen.getByLabelText('发送状态').textContent).toBe('空闲')
  expect(screen.getByLabelText('附件数量').textContent).toBe('1')
  expect(vault.getSnapshot().draft).toMatchObject({
    ...original,
    files: [expect.objectContaining(existing)],
    key: expect.any(String),
    sending: false,
  })
  expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:existing')
  expect(recordingPreview).not.toHaveBeenCalled()
  await act(async () => notesUpload.resolve({ id: 'notes', kind: 'document' } as never))
  await flush()
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await flush()
  expect(sendMessage).toHaveBeenLastCalledWith(
    expect.objectContaining({
      text: original.text,
      attachmentIds: ['notes'],
      replyTo: original.replyTo,
      workReference: original.workReference,
    }),
    expect.any(String),
  )
})
it('carries the unsent draft into a conversation created by a voice-only message', async () => {
  const { vault } = view('bar', 0, true)
  const button = await hold(screen.getByRole('button', { name: '点击录音，长按发送' }))
  fireEvent.pointerUp(button, pointer)
  act(() => Recorder.latest.finish())
  await flush()
  expect(sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({ newConversation: true, text: '', attachmentIds: ['voice'] }),
    expect.any(String),
  )
  expect(vault.getSnapshot().draft).toBeUndefined()
  expect(vault.getSnapshot()['composer:chat']).toMatchObject({
    text: '原来的文字',
    files: [],
    sending: false,
  })
})
it('only shows a notice when automatic voice submission is blocked', async () => {
  view('bar', 1)
  const button = await hold(screen.getByRole('button', { name: '点击录音，长按发送' }))
  fireEvent.pointerUp(button, pointer)
  act(() => Recorder.latest.finish())
  await flush()
  expect(screen.getByLabelText('发送状态').textContent).toBe('空闲')
  expect(screen.queryByRole('button', { name: '播放语音 1' })).toBeNull()
  expect(screen.getByLabelText('附件数量').textContent).toBe('0')
  expect(notify).toHaveBeenCalledExactlyOnceWith('语音发送未完成')
  expect(uploadAttachment).not.toHaveBeenCalled()
  expect(sendMessage).not.toHaveBeenCalled()
})
it('keeps a manually sent recording in the draft after failure', async () => {
  vi.mocked(uploadAttachment).mockRejectedValue(new Error('网络中断'))
  view()
  fireEvent.click(mic())
  await flush()
  fireEvent.click(screen.getByRole('button', { name: '停止录音 · 0 秒' }))
  act(() => Recorder.latest.finish())
  await flush()
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await flush()
  expect(screen.getByRole('button', { name: '播放语音 1' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '重试上传语音 1' })).toBeTruthy()
  expect(screen.getByText(/文件上传失败，请重试或移除/)).toBeTruthy()
  expect(sendMessage).not.toHaveBeenCalled()
  expect(notify).not.toHaveBeenCalled()
})
