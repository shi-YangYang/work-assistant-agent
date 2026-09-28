import type { Work, WorkReferenceView } from '@paa/api-contracts'
import { epoch, isCancelled } from '@web/api/client'
import { readReferenceWork } from '../api/requests'
import type { Composer } from '../lib/audio-capture'
import { useWorkspace } from '@web/lib/workspace'
import { identityScope } from '@web/lib/session-drafts'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { useSearchParams } from 'react-router'
import { flushSync } from 'react-dom'

export function useWorkReference(
  composerKey: string,
  locked: boolean,
  input: RefObject<HTMLTextAreaElement | null>,
) {
  const { drafts, setDraft, identity } = useWorkspace()
  const [params, setParams] = useSearchParams()
  const entry = params.get('workId') || ''
  const [pickerOpen, setPickerOpen] = useState(false)
  const [revision, setRevision] = useState(0)
  const token = `${identityScope(identity)}:${epoch}:${composerKey}:${entry}:${revision}`
  const current = useRef(token)
  useLayoutEffect(() => {
    current.current = token
  }, [token])
  const [loaded, setLoaded] = useState<{
    token: string
    reference?: WorkReferenceView
    error?: Error
  } | null>(null)
  useEffect(() => {
    if (!entry) return
    const controller = new AbortController()
    void readReferenceWork(entry, controller.signal)
      .then((work) => {
        if (current.current !== token || controller.signal.aborted) return
        if (work.ownerId !== identity.member.id) throw new Error('只能引用本人的工作')
        setLoaded({ token, reference: { workId: work.id, title: work.title } })
      })
      .catch((error: Error) => {
        if (current.current === token && !controller.signal.aborted && !isCancelled(error))
          setLoaded({ token, error })
      })
    return () => controller.abort()
  }, [entry, token, identity.member.id])
  const reference = loaded?.token === token ? loaded.reference : undefined
  const draft = drafts[composerKey] as Composer | undefined
  useEffect(() => {
    if (!reference || locked || draft?.pending || draft?.sending) return
    setDraft(composerKey, (previous: Composer | undefined) => ({
      ...(previous ?? { text: '', files: [] }),
      workReference: reference,
      key: crypto.randomUUID(),
      submissionPersonaId: undefined,
    }))
    const next = new URLSearchParams(params)
    next.delete('workId')
    setParams(next, { replace: true })
    input.current?.focus()
  }, [
    reference,
    locked,
    draft?.pending,
    draft?.sending,
    composerKey,
    setDraft,
    params,
    setParams,
    input,
  ])

  function change(reference?: WorkReferenceView) {
    if (locked) return
    setDraft(composerKey, (previous: Composer | undefined) => {
      if (previous?.pending || previous?.sending) return previous
      const next: Composer = {
        ...(previous ?? { text: '', files: [] }),
        workReference: reference,
        key: crypto.randomUUID(),
        submissionPersonaId: undefined,
      }
      return next.text ||
        next.files.length ||
        next.replyTo ||
        next.deliverableReference ||
        next.personaId ||
        next.executionMode ||
        next.workReference
        ? next
        : undefined
    })
    // A manual choice supersedes a delayed entry request.
    if (entry) {
      const next = new URLSearchParams(params)
      next.delete('workId')
      setParams(next, { replace: true })
    }
    input.current?.focus()
  }
  return {
    pickerOpen,
    setPickerOpen,
    loading: !!entry && loaded?.token !== token,
    error: loaded?.token === token ? loaded.error : undefined,
    retry: () => setRevision((value) => value + 1),
    remove: () => change(),
    select: (work: Work) => {
      flushSync(() => setPickerOpen(false))
      change({ workId: work.id, title: work.title })
    },
  }
}
