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
  const sendOnFinish = useRef(false)
  const pendingSend = useRef<File | null>(null)
  useEffect(() => {
    active.current = true
    const controller = new AudioCapture({
      state: (state) => {
        if (state === 'requesting') {
          sendOnFinish.current = false
          pendingSend.current = null
        }
        setCaptureState(state)
        if (state === 'recording') setSeconds(0)
        setDraft('recording', state !== 'idle' ? true : undefined)
      },
      error: (error) => {
        sendOnFinish.current = false
        setSendError(error)
      },
      file: (file) => {
        if (active.current && sendOnFinish.current) pendingSend.current = file
        sendOnFinish.current = false
        setDraft(composerKey, (previous: Composer | undefined) =>
          appendRecordedFile(previous, file),
        )
      },
    })
    capture.current = controller
    const guard = () => {
      if (document.hidden) {
        sendOnFinish.current = false
        pendingSend.current = null
        controller.stop()
      }
    }
    document.addEventListener('visibilitychange', guard)
    return () => {
      active.current = false
      sendOnFinish.current = false
      pendingSend.current = null
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
      sendOnFinish.current = false
      controller?.stop()
      setLimitError('已达到 3 分钟录音上限，已保留录音片段，可以试听后发送。')
    }, 180000)
    return () => {
      clearInterval(timer)
      clearTimeout(limit)
    }
  }, [recording, setLimitError])
  return {
    captureState,
    recording,
    capturing,
    seconds,
    capture,
    active,
    pendingSend,
    stop: (send = false) => {
      sendOnFinish.current = send && captureState === 'recording'
      capture.current?.stop()
    },
    cancel: () => {
      sendOnFinish.current = false
      pendingSend.current = null
      capture.current?.cancel()
    },
  }
}
