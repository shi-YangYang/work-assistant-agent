import type { Attachment } from '../shared/company-contracts'

type PendingFile = { id: string; file: File; url: string; attachment?: Attachment }
export type Composer = { text: string; files: PendingFile[]; key: string; replyTo?: string }

export function appendRecordedFile(previous: Composer | undefined, file: File): Composer {
  const current = previous ?? { text: '', files: [], key: '' }
  return {
    ...current,
    key: crypto.randomUUID(),
    files: [...current.files, { id: crypto.randomUUID(), file, url: URL.createObjectURL(file) }],
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

  async start() {
    if (this.disposed || this.pending || this.session) return
    const generation = ++this.generation
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
      recorder.ondataavailable = (event) => {
        if (!session.finished && session.keep && event.data.size) session.chunks.push(event.data)
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
    } catch {
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
      this.callbacks.error('无法使用麦克风，请允许浏览器录音，或使用文字和语音文件')
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
