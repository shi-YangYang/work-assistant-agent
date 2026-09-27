import type { CompanyModel, CompanyPreset } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { deleteModelService, saveModelService } from '@web/features/model-services/api/requests'
import { useServiceCheck } from '@web/features/model-services/hooks/useServiceCheck'
import { useServiceDraftSession } from '@web/features/model-services/hooks/useServiceDraftSession'
import type { Purpose } from '@web/features/model-services/types'
import { purposeNames } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import {
  appendServiceModels,
  cleanServiceDraft,
  modelApiKeyError,
  validateServiceModels,
} from '@web/features/model-services/utils/service-drafts'
import {
  matchModelProtocol,
  requireModelProtocols,
  resolveModelProtocol,
} from '@web/features/model-services/utils/service-presets'
import { useWorkspace } from '@web/lib/workspace'
import { useState } from 'react'

export function useModelServiceController() {
  const workspace = useWorkspace()
  const [tab, setTab] = useState<'services' | 'routing'>('services')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<Error | string>('')
  const [conflict, setConflict] = useState(false)
  const [activeModel, setActiveModel] = useState('')
  const [picker, setPicker] = useState<'catalog' | 'manual' | null>(null)
  const [modelOpen, setModelOpen] = useState(false)
  const [assignServiceId, setAssignServiceId] = useState('')
  const [testPurpose, setTestPurpose] = useState<Purpose>('assistant')
  const [removeOpen, setRemoveOpen] = useState(false)
  const [preset, setPreset] = useState<CompanyPreset | null>(null)
  const [presetJson, setPresetJson] = useState('{}')
  const session = useServiceDraftSession()
  const {
    resource,
    services,
    drafts,
    draft,
    allServices,
    dirty,
    connectionReady,
    update: updateDraft,
    changeAddress: changeDraftAddress,
    capture,
  } = session
  const { selected, setSelected, select: selectDraft } = session.selection
  const { keys, setKeys, blocker } = session.credentials
  const { generationRef, alive } = session.lifecycle
  const currentModel = draft?.models.find((m) => m.id === activeModel)
  const model =
    currentModel && draft ? resolveModelProtocol(draft.baseUrl, currentModel) : undefined
  const automaticMatch =
    model?.protocolMode === 'auto' && draft ? matchModelProtocol(draft.baseUrl, model.model) : null
  const updateModel = (next: CompanyModel) =>
    draft && update({ ...draft, models: draft.models.map((m) => (m.id === next.id ? next : m)) })
  const handleError = (e: unknown) => {
    setError(e as Error)
    if (e instanceof ApiError && e.status === 409) setConflict(true)
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      setKeys({})
      generationRef.current++
      window.dispatchEvent(new Event('paa-session-expired'))
    }
  }
  const {
    catalog,
    setCatalog,
    check,
    setCheck,
    checkOpen,
    setCheckOpen,
    testOpen,
    setTestOpen,
    request,
  } = useServiceCheck({
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
  })
  const resetFeedback = () => {
    setCatalog(null)
    setCheck(null)
    setError('')
    setConflict(false)
  }
  const update = (next: ServiceDraft) => {
    resetFeedback()
    updateDraft(next)
  }
  const select = (id: string | null) => {
    resetFeedback()
    setActiveModel('')
    selectDraft(id)
  }
  const changeAddress: typeof changeDraftAddress = (...args) => {
    resetFeedback()
    changeDraftAddress(...args)
  }
  const save = async (target = draft, assign = false): Promise<boolean> => {
    if (!target) return false
    const generation = generationRef.current
    setBusy('save')
    setError('')
    try {
      const keyError = modelApiKeyError(keys[target.id] || '')
      if (keyError) throw new Error(keyError)
      validateServiceModels(target.models)
      const payload =
        target === draft
          ? capture()
          : {
              name: target.name,
              baseUrl: target.baseUrl,
              models: requireModelProtocols(target.baseUrl, target.models),
              expectedRevision: target.revision,
              apiKey: keys[target.id] || '',
            }
      const saved = await saveModelService(target, payload, target.revision ? 'PATCH' : 'POST')
      if (!alive.current || generation !== generationRef.current) return false
      workspace.setDraft('modelServices', (previous: Record<string, ServiceDraft> = {}) => {
        const next = { ...previous }
        delete next[target.id]
        next[saved.id] = cleanServiceDraft({ ...saved, providerPreset: target.providerPreset })
        return next
      })
      setKeys((previous) => {
        const values = { ...previous }
        delete values[target.id]
        return values
      })
      if (selected === target.id) setSelected(saved.id)
      setCheck(null)
      setConflict(false)
      generationRef.current++
      resource.refresh()
      workspace.notify('模型服务已保存')
      if (assign) {
        setAssignServiceId(saved.id)
        setTab('routing')
      }
      return true
    } catch (e) {
      if (alive.current) handleError(e)
      return false
    } finally {
      if (alive.current) setBusy('')
    }
  }
  const remove = async () => {
    if (!draft) return
    const generation = generationRef.current
    setBusy('delete')
    try {
      if (draft.revision) await deleteModelService(draft, { expectedRevision: draft.revision })
      if (!alive.current || generation !== generationRef.current) return
      const next = { ...drafts }
      delete next[draft.id]
      workspace.setDraft('modelServices', Object.keys(next).length ? next : undefined)
      setKeys((previous) => {
        const values = { ...previous }
        delete values[draft.id]
        return values
      })
      select(null)
      setRemoveOpen(false)
      if (draft.revision) resource.refresh()
    } catch (e) {
      handleError(e)
    } finally {
      setBusy('')
    }
  }
  const createService = () => {
    const fresh: ServiceDraft = {
      id: crypto.randomUUID(),
      name: '新服务',
      baseUrl: '',
      models: [],
      revision: 0,
      hasKey: false,
    }
    update(fresh)
    select(fresh.id)
    setTab('services')
  }
  const addModels = (ids: string[]) => {
    if (!draft) return
    try {
      const next = appendServiceModels(draft, ids)
      const added = next.models.slice(draft.models.length)
      if (!added.length) throw new Error('这些模型已经添加，请选择其它模型。')
      update(next)
      setPicker(null)
      const unresolved = added.find(
        (m) => m.protocolMode === 'auto' && !matchModelProtocol(draft.baseUrl, m.model).protocol,
      )
      if (unresolved) {
        setActiveModel(unresolved.id)
        setModelOpen(true)
      }
      workspace.notify(`已添加 ${added.length} 个模型，保存服务后生效`)
    } catch (failure) {
      setError(failure as Error)
    }
  }
  const usesFor = (serviceId: string, modelId?: string) => {
    const routing = resource.data?.routing
    return (['assistant', 'report', 'asr'] as const)
      .filter((purpose) => {
        const choice = routing?.[purpose] === 'follow' ? routing.assistant : routing?.[purpose]
        return (
          choice &&
          typeof choice === 'object' &&
          choice.serviceId === serviceId &&
          (!modelId || choice.modelId === modelId)
        )
      })
      .map((purpose) => purposeNames[purpose])
  }
  const changeKey = (value: string) => {
    if (!draft) return
    generationRef.current++
    resetFeedback()
    setKeys({ ...keys, [draft.id]: value })
  }

  return {
    workspace,
    tab,
    setTab,
    busy,
    setBusy,
    error,
    setError,
    conflict,
    setActiveModel,
    picker,
    setPicker,
    modelOpen,
    setModelOpen,
    assignServiceId,
    setAssignServiceId,
    testPurpose,
    setTestPurpose,
    removeOpen,
    setRemoveOpen,
    preset,
    setPreset,
    presetJson,
    setPresetJson,
    resource,
    services,
    drafts,
    draft,
    allServices,
    dirty,
    connectionReady,
    keys,
    setKeys,
    blocker,
    model,
    automaticMatch,
    updateModel,
    handleError,
    catalog,
    check,
    checkOpen,
    setCheckOpen,
    testOpen,
    setTestOpen,
    request,
    update,
    select,
    changeAddress,
    save,
    remove,
    createService,
    addModels,
    usesFor,
    changeKey,
  }
}
