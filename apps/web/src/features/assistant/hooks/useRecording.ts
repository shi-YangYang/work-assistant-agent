import type { CaptureState, Composer } from '@web/features/assistant/lib/audio-capture'
import { appendRecordedFile, AudioCapture } from '@web/features/assistant/lib/audio-capture'
import { useEffect, useRef, useState } from 'react'

import type { WorkspaceState } from '@web/lib/workspace'
export function useRecording(
  composerKey: string,
  setDraft: WorkspaceState['setDraft'],
  setSendError: (error: Error | string) => void,
  setLimitError: (error: string) => void,
) {
  const [captureState, setCaptureState] = useState<CaptureState>('idle')
  const recording = captureState === 'recording'
  const capturing = captureState !== 'idle'
  const [seconds, setSeconds] = useState(0)
  const capture = useRef<AudioCapture | null>(null)
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    const controller = new AudioCapture({
      state: (state) => {
        setCaptureState(state)
        if (state === 'recording') setSeconds(0)
        setDraft('recording', state !== 'idle' ? true : undefined)
      },
      error: setSendError,
      file: (file) => {
        setDraft(composerKey, (previous: Composer | undefined) =>
          appendRecordedFile(previous, file),
        )
      },
    })
    capture.current = controller
    const guard = () => {
      if (document.hidden) controller.stop()
    }
    document.addEventListener('visibilitychange', guard)
    return () => {
      active.current = false
      controller.dispose()
      capture.current = null
      setDraft('recording', undefined)
      document.removeEventListener('visibilitychange', guard)
    }
  }, [setDraft, composerKey, setSendError])
  useEffect(() => {
    if (!recording) return
    const controller = capture.current
    const timer = setInterval(() => setSeconds((n) => n + 1), 1000)
    const limit = setTimeout(() => {
      controller?.stop()
      setLimitError('已达到 3 分钟录音上限，已保留录音片段，可以试听后发送。')
    }, 180000)
    return () => {
      clearInterval(timer)
      clearTimeout(limit)
    }
  }, [recording, setLimitError])
  return { captureState, recording, capturing, seconds, capture, active }
}
