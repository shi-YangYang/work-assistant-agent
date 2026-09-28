import { modelServicesPath } from '@web/features/model-services/api/requests'
import type { Listing } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import {
  cleanServiceDraft,
  modelApiKeyError,
  sameServiceAddress,
  serviceHasChanges,
  validateServiceModels,
} from '@web/features/model-services/utils/service-drafts'
import type { ServicePreset } from '@web/features/model-services/utils/service-presets'
import {
  requireModelProtocols,
  resolveModelProtocol,
} from '@web/features/model-services/utils/service-presets'
import { useResource } from '@web/hooks/useResource'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { useBlocker } from 'react-router'

function readSelection(scope: string) {
  let id: string | null = null
  try {
    id = localStorage.getItem(scope)
  } catch {
    /* Storage may be disabled. */
  }
  return { scope, id }
}

function rememberSelection(scope: string, id: string | null) {
  try {
    if (id) localStorage.setItem(scope, id)
    else localStorage.removeItem(scope)
  } catch {
    /* Selection still works in memory. */
  }
}

export function useServiceDraftSession() {
  const workspace = useWorkspace()
  const resource = useResource<Listing>(modelServicesPath())
  const selectionKey = `paa:model-service:${identityScope(workspace.identity)}`
  const drafts = (workspace.drafts.modelServices as Record<string, ServiceDraft>) || {}
  const services = resource.data?.services ?? []
  const allServices = [
    ...services,
    ...Object.values(drafts).filter((d) => !d.revision && !services.some((s) => s.id === d.id)),
  ]
  const [selection, changeSelection] = useState(() => readSelection(selectionKey))
  const preference = selection.scope === selectionKey ? selection : readSelection(selectionKey)
  const selected =
    !resource.data || allServices.some((service) => service.id === preference.id)
      ? preference.id
      : allServices.length === 1
        ? allServices[0].id
        : null
  // Reconcile derived selection before children render; effects only persist the committed choice.
  if (selection.scope !== selectionKey || selection.id !== selected)
    changeSelection({ scope: selectionKey, id: selected })
  const setSelected = (id: string | null) => {
    changeSelection({ scope: selectionKey, id })
    rememberSelection(selectionKey, id)
  }
  useEffect(() => {
    if (resource.data) rememberSelection(selectionKey, selected)
  }, [selectionKey, selected, resource.data])
  const [credentials, changeCredentials] = useState<{
    scope: string
    values: Record<string, string>
  }>({ scope: selectionKey, values: {} })
  const keys = credentials.scope === selectionKey ? credentials.values : {}
  const setKeys: Dispatch<SetStateAction<Record<string, string>>> = (next) =>
    changeCredentials((previous) => {
      const current = previous.scope === selectionKey ? previous.values : {}
      return { scope: selectionKey, values: typeof next === 'function' ? next(current) : next }
    })
  const draft: ServiceDraft | undefined = selected
    ? (drafts[selected] ?? services.find((s) => s.id === selected))
    : undefined
  const savedService = services.find((service) => service.id === draft?.id)
  const dirty = !!draft && (serviceHasChanges(draft, savedService) || !!keys[draft.id])
  const connectionReady =
    !!draft?.name.trim() &&
    !!draft.baseUrl.trim() &&
    (!!keys[draft.id] || (draft.hasKey && sameServiceAddress(draft.baseUrl, savedService?.baseUrl)))
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
  }, [hasKeys, selectionKey])
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
    if (!sameServiceAddress(baseUrl, draft.baseUrl))
      setKeys((previous) => ({ ...previous, [draft.id]: '' }))
    update({
      ...draft,
      name: name || draft.name,
      baseUrl,
      providerPreset,
      models: sameServiceAddress(baseUrl, draft.baseUrl)
        ? draft.models
        : draft.models.map((model) => ({ ...model, contextCapability: undefined })),
    })
  }
  const capture = (requireProtocols = true) => {
    if (!draft) throw new Error('请选择服务')
    const keyError = modelApiKeyError(keys[draft.id] || '')
    if (keyError) throw new Error(keyError)
    validateServiceModels(draft.models)
    return {
      name: draft.name,
      baseUrl: draft.baseUrl,
      models: requireProtocols ? requireModelProtocols(draft.baseUrl, draft.models) : draft.models,
      expectedRevision: draft.revision,
      apiKey: keys[draft.id] || '',
    }
  }
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
