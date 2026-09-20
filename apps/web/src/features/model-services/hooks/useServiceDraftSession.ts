import { modelServicesPath } from '@web/features/model-services/api/requests'
import type { Listing } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import {
  cleanServiceDraft,
  serviceHasChanges,
  validateCompanyParameters,
} from '@web/features/model-services/utils/service-drafts'
import type { ServicePreset } from '@web/features/model-services/utils/service-presets'
import {
  requireModelProtocols,
  resolveModelProtocol,
} from '@web/features/model-services/utils/service-presets'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { useEffect, useRef, useState } from 'react'
import { useBlocker } from 'react-router'

export function useServiceDraftSession() {
  const workspace = useWorkspace()
  const resource = useResource<Listing>(modelServicesPath())
  const [selected, setSelected] = useState<string | null>(null)
  const [keys, setKeys] = useState<Record<string, string>>({})
  const drafts = (workspace.drafts.modelServices as Record<string, ServiceDraft>) || {}
  const services = resource.data?.services ?? []
  const draft: ServiceDraft | undefined = selected
    ? (drafts[selected] ?? services.find((s) => s.id === selected))
    : undefined
  const savedService = services.find((service) => service.id === draft?.id)
  const dirty = !!draft && (serviceHasChanges(draft, savedService) || !!keys[draft.id])
  const connectionReady =
    !!draft?.name.trim() &&
    !!draft.baseUrl.trim() &&
    (!!keys[draft.id] || (draft.hasKey && draft.baseUrl === savedService?.baseUrl))
  const generationRef = useRef(0)
  const alive = useRef(true)
  const hasKeys = Object.values(keys).some(Boolean)
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      hasKeys && currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    alive.current = true
    const epoch = generationRef
    const before = (event: BeforeUnloadEvent) => {
      if (hasKeys) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', before)
    return () => {
      alive.current = false
      epoch.current++
      window.removeEventListener('beforeunload', before)
    }
  }, [hasKeys])
  const update = (next: ServiceDraft) => {
    generationRef.current++
    workspace.setDraft('modelServices', {
      ...drafts,
      [next.id]: cleanServiceDraft({
        ...next,
        models: next.models.map((m) => resolveModelProtocol(next.baseUrl, m)),
      }),
    })
  }
  const select = (id: string | null) => {
    generationRef.current++
    setSelected(id)
  }
  const changeAddress = (baseUrl: string, providerPreset: ServicePreset, name = draft?.name) => {
    if (!draft) return
    if (baseUrl !== draft.baseUrl) setKeys((previous) => ({ ...previous, [draft.id]: '' }))
    update({ ...draft, name: name || draft.name, baseUrl, providerPreset })
  }
  const capture = (requireProtocols = true) => {
    if (!draft) throw new Error('请选择服务')
    for (const m of draft.models)
      for (const p of m.presets)
        validateCompanyParameters(
          p.mode === 'simple' ? { reasoning_effort: p.value } : p.parameters,
        )
    return {
      name: draft.name,
      baseUrl: draft.baseUrl,
      models: requireProtocols ? requireModelProtocols(draft.baseUrl, draft.models) : draft.models,
      expectedRevision: draft.revision,
      apiKey: keys[draft.id] || '',
    }
  }
  const allServices = [
    ...services,
    ...Object.values(drafts).filter((d) => !d.revision && !services.some((s) => s.id === d.id)),
  ]
  return {
    resource,
    services,
    drafts,
    draft,
    allServices,
    dirty,
    connectionReady,
    selection: { selected, setSelected, select },
    credentials: { keys, setKeys, blocker },
    lifecycle: { generationRef, alive },
    update,
    changeAddress,
    capture,
  }
}
