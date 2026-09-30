import type { DeliverableFile } from '@paa/api-contracts'
import { epoch, isCancelled } from '@web/api/client'
import { useEffect, useRef, useState } from 'react'
import { readGeneratedFile } from '../api/deliverables'

export function useGeneratedFile(deliverableId: string, revision: number, file: DeliverableFile) {
  const generation = epoch
  const scope = JSON.stringify([generation, deliverableId, revision, file])
  const active = useRef<{ scope: string; requests: Set<AbortController> } | null>(null)
  const downloads = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const [busy, setBusy] = useState<string | null>(null)
  const [failure, setFailure] = useState<{ scope: string; error: Error } | null>(null)
  useEffect(() => {
    const session = { scope, requests: new Set<AbortController>() }
    const urls = downloads.current
    active.current = session
    return () => {
      if (active.current === session) active.current = null
      session.requests.forEach((controller) => controller.abort())
      urls.forEach((timer, url) => {
        clearTimeout(timer)
        URL.revokeObjectURL(url)
      })
      urls.clear()
    }
  }, [scope])

  async function download() {
    const session = active.current
    if (!session || session.scope !== scope || session.requests.size || epoch !== generation) return
    const controller = new AbortController()
    session.requests.add(controller)
    setBusy(scope)
    setFailure(null)
    try {
      // Always authorize downloads again, even when an image preview is already loaded.
      const blob = await readGeneratedFile(deliverableId, revision, file, controller.signal)
      if (active.current !== session || controller.signal.aborted || epoch !== generation) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = file.name
      downloads.current.set(
        url,
        setTimeout(() => {
          downloads.current.delete(url)
          URL.revokeObjectURL(url)
        }, 1000),
      )
      document.body.append(link)
      link.click()
      link.remove()
    } catch (error) {
      if (active.current === session && epoch === generation && !isCancelled(error))
        setFailure({ scope, error: error instanceof Error ? error : new Error('文件下载失败。') })
    } finally {
      session.requests.delete(controller)
      if (active.current === session && epoch === generation) setBusy(null)
    }
  }
  return {
    download,
    busy: busy === scope,
    error: failure?.scope === scope ? failure.error : '',
  }
}

export function useGeneratedImage(deliverableId: string, revision: number, file: DeliverableFile) {
  const generation = epoch
  const scope = JSON.stringify([generation, deliverableId, revision, file])
  const [loaded, setLoaded] = useState<{ scope: string; url: string } | null>(null)
  const [failure, setFailure] = useState<{ scope: string; error: Error } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const { id, name, mimeType, size, url: source } = file
  useEffect(() => {
    const controller = new AbortController()
    let url = ''
    void readGeneratedFile(
      deliverableId,
      revision,
      { id, name, mimeType, size, url: source },
      controller.signal,
    ).then(
      (blob) => {
        if (controller.signal.aborted || epoch !== generation) return
        url = URL.createObjectURL(blob)
        setLoaded({ scope, url })
        setFailure(null)
      },
      (error) => {
        if (controller.signal.aborted || epoch !== generation || isCancelled(error)) return
        setLoaded(null)
        setFailure({ scope, error: error instanceof Error ? error : new Error('图片读取失败。') })
      },
    )
    return () => {
      controller.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [deliverableId, revision, id, name, mimeType, size, source, generation, scope, attempt])
  return {
    url: loaded?.scope === scope ? loaded.url : '',
    error: failure?.scope === scope ? failure.error : '',
    retry: () => setAttempt((value) => value + 1),
  }
}
