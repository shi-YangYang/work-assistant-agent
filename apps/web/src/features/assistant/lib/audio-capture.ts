import type { Attachment } from '@paa/api-contracts'

type PendingFile = {
  id: string
  file: File
  url: string
  recorded?: boolean
  attachment?: Attachment
  failed?: boolean
}

export type Composer = {
  text: string
  files: PendingFile[]
  key: string
  replyTo?: string
  sending?: boolean
  uploading?: string
  pending?: {
    key: string
    body: {
      conversationId?: string
      newConversation?: boolean
      text: string
      attachmentIds: string[]
      voiceCommandAttachmentId?: string
      replyTo: string | null
    }
  }
}

export function appendRecordedFile(previous: Composer | undefined, file: File): Composer {
  const current = previous ?? { text: '', files: [], key: '' }
  return {
    ...current,
    key: crypto.randomUUID(),
    files: [
      ...current.files,
      { id: crypto.randomUUID(), file, url: URL.createObjectURL(file), recorded: true },
    ],
  }
}

export type CaptureState = 'idle' | 'requesting' | 'recording' | 'stopping'

type CaptureCallbacks = {
  state: (state: CaptureState) => void
  file: (file: File) => void
  error: (message: string) => void
}

type Session = {
  stream: MediaStream
  recorder: MediaRecorder
  chunks: BlobPart[]
  keep: boolean
  finished: boolean
}

// Own both the pending permission request and every acquired stream. React may
// unmount before permission or MediaRecorder's final events arrive.
export class AudioCapture {
  private generation = 0
  private disposed = false
  private pending = false
  private session: Session | null = null

  constructor(private callbacks: CaptureCallbacks) {}

  async start(maxBytes = 20 * 1024 * 1024) {
    if (this.disposed || this.pending || this.session) return
    const generation = ++this.generation
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
      this.callbacks.error('此地址不是安全连接，无法录音。请使用 HTTPS，或发送文字、语音文件。')
      return
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      this.callbacks.error('当前浏览器不支持录音，请输入文字或选择语音文件。')
      return
    }
    this.pending = true
    this.callbacks.state('requesting')
    let stream: MediaStream | undefined
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (this.disposed || generation !== this.generation) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find((type) =>
        MediaRecorder.isTypeSupported(type),
      )
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const session: Session = { stream, recorder, chunks: [], keep: true, finished: false }
      this.session = session
      let bytes = 0
      recorder.ondataavailable = (event) => {
        if (!session.finished && session.keep && event.data.size) {
          session.chunks.push(event.data)
          bytes += event.data.size
          if (bytes >= maxBytes && recorder.state !== 'inactive') {
            this.callbacks.error(
              '录音已达到附件容量上限，已保留录音；请移除其他附件或重新录制后发送。',
            )
            this.stop()
          }
        }
      }
      recorder.onstop = () => this.finish(session)
      recorder.onerror = () => {
        if (this.session !== session || session.finished) return
        if (!this.disposed) this.callbacks.error('录音中断，请检查麦克风后重试')
        this.stop()
      }
      recorder.start(1000)
      this.pending = false
      this.callbacks.state('recording')
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop())
      if (this.disposed || generation !== this.generation) return
      const session = this.session
      if (session) {
        session.keep = false
        this.stop()
        this.finish(session)
      }
      this.pending = false
      this.callbacks.state('idle')
      this.callbacks.error(microphoneError(error))
    }
  }

  stop() {
    if (this.pending) {
      ++this.generation
      this.pending = false
      if (!this.disposed) this.callbacks.state('idle')
    }
    const session = this.session
    if (!session || session.finished) return
    if (!this.disposed) this.callbacks.state('stopping')
    try {
      if (session.recorder.state !== 'inactive') session.recorder.stop()
      else this.finish(session)
    } catch {
      this.finish(session)
    } finally {
      session.stream.getTracks().forEach((track) => track.stop())
    }
  }

  dispose() {
    this.disposed = true
    ++this.generation
    this.stop()
  }

  private finish(session: Session) {
    if (session.finished) return
    session.finished = true
    session.stream.getTracks().forEach((track) => track.stop())
    if (this.session === session) {
      this.session = null
      if (!this.disposed) this.callbacks.state('idle')
    }
    if (session.keep) {
      const file = new File(
        session.chunks,
        `语音.${session.recorder.mimeType.includes('mp4') ? 'mp4' : 'webm'}`,
        { type: session.recorder.mimeType },
      )
      // Also preserve captured content when navigation stopped this session.
      if (file.size) this.callbacks.file(file)
    }
  }
}

export function microphoneError(error: unknown) {
  const name = error instanceof Error ? error.name : ''
  if (['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(name))
    return '麦克风权限未获允许，请在浏览器设置中允许录音，或输入文字、选择语音文件。'
  if (['NotFoundError', 'DevicesNotFoundError'].includes(name))
    return '未找到麦克风，请连接设备，或输入文字、选择语音文件。'
  if (['NotReadableError', 'TrackStartError', 'AbortError'].includes(name))
    return '麦克风暂时不可用，可能正被其他应用占用。请关闭占用后重试，或输入文字、选择语音文件。'
  return '无法开始录音，请检查麦克风，或输入文字、选择语音文件。'
}
