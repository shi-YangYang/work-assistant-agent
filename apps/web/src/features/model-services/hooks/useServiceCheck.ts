import type { CompanyModel, ModelCheck } from '@paa/api-contracts'
import { checkServiceConfiguration } from '@web/features/model-services/api/requests'
import { useServiceDraftSession } from '@web/features/model-services/hooks/useServiceDraftSession'
import type { Purpose } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { useState } from 'react'

import type { Dispatch, RefObject, SetStateAction } from 'react'
export function useServiceCheck({
  draft,
  model,
  testPurpose,
  capture,
  generationRef,
  alive,
  setBusy,
  setError,
  setConflict,
  handleError,
}: {
  draft: ServiceDraft | undefined
  model: CompanyModel | undefined
  testPurpose: Purpose
  capture: ReturnType<typeof useServiceDraftSession>['capture']
  generationRef: RefObject<number>
  alive: RefObject<boolean>
  setBusy: Dispatch<SetStateAction<string>>
  setError: Dispatch<SetStateAction<Error | string>>
  setConflict: Dispatch<SetStateAction<boolean>>
  handleError: (error: unknown) => void
}) {
  const [catalog, setCatalog] = useState<{
    models: string[]
    source: string
    truncated: boolean
  } | null>(null)
  const [checkOpen, setCheckOpen] = useState(false)
  const [check, setCheck] = useState<ModelCheck | null>(null)
  const [testOpen, setTestOpen] = useState(false)
  const request = async (kind: 'models' | 'test') => {
    if (!draft) return
    const requestGeneration = ++generationRef.current
    const version = crypto.randomUUID()
    setBusy(kind)
    setError('')
    setConflict(false)
    try {
      const value = await checkServiceConfiguration(kind, {
        ...capture(kind === 'test'),
        serviceId: draft.revision ? draft.id : null,
        modelId: model?.id ?? null,
        purpose: testPurpose,
        draftVersion: version,
      })
      if (
        !alive.current ||
        requestGeneration !== generationRef.current ||
        value.draftVersion !== version
      )
        return
      if ('checks' in value) {
        setCheck(value)
        setCheckOpen(true)
      } else setCatalog(value)
    } catch (e) {
      if (alive.current && requestGeneration === generationRef.current) handleError(e)
    } finally {
      if (alive.current) setBusy('')
      setTestOpen(false)
    }
  }
  return {
    catalog,
    setCatalog,
    check,
    setCheck,
    checkOpen,
    setCheckOpen,
    testOpen,
    setTestOpen,
    request,
  }
}
