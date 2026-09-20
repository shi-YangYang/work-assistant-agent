import type { CompanyModel, CompanyPreset } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { deleteModelService, saveModelService } from '@web/features/model-services/api/requests'
import { EnvironmentServices } from '@web/features/model-services/components/EnvironmentServices'
import { ModelCheckResult } from '@web/features/model-services/components/ModelCheckResult'
import { ModelOptions } from '@web/features/model-services/components/ModelOptions'
import { ModelPicker } from '@web/features/model-services/components/ModelPicker'
import { ModelTestDialog } from '@web/features/model-services/components/ModelTestDialog'
import { ReasoningPresetEditor } from '@web/features/model-services/components/ReasoningPresetEditor'
import { RemoveServiceDialog } from '@web/features/model-services/components/RemoveServiceDialog'
import { Routing } from '@web/features/model-services/components/Routing'
import { ServiceConnectionFields } from '@web/features/model-services/components/ServiceConnectionFields'
import { ServiceEditor } from '@web/features/model-services/components/ServiceEditor'
import { ServiceList } from '@web/features/model-services/components/ServiceList'
import { ServiceModelLibrary } from '@web/features/model-services/components/ServiceModelLibrary'
import { UnsavedKeysDialog } from '@web/features/model-services/components/UnsavedKeysDialog'
import { useServiceCheck } from '@web/features/model-services/hooks/useServiceCheck'
import { useServiceDraftSession } from '@web/features/model-services/hooks/useServiceDraftSession'
import type { Purpose } from '@web/features/model-services/types'
import { purposeNames } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import {
  appendServiceModels,
  cleanServiceDraft,
} from '@web/features/model-services/utils/service-drafts'
import {
  matchModelProtocol,
  requireModelProtocols,
  resolveModelProtocol,
} from '@web/features/model-services/utils/service-presets'
import { useWorkspace } from '@web/lib/workspace'
import { Check, Plus } from 'lucide-react'
import { useState } from 'react'

export function ModelServices() {
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
    setBusy('save')
    setError('')
    try {
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
      if (!alive.current) return false
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
    setBusy('delete')
    try {
      if (draft.revision) await deleteModelService(draft, { expectedRevision: draft.revision })
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
  return (
    <div className="settings-page model-management">
      <div className="page-heading">
        <div>
          <h2>模型服务管理</h2>
        </div>
        {!draft && tab === 'services' && (
          <button className="primary" disabled={!!busy || !resource.data} onClick={createService}>
            <Plus size={16} /> 添加服务
          </button>
        )}
      </div>
      <div className="tabs" role="tablist" aria-label="模型管理页面">
        <button
          role="tab"
          aria-selected={tab === 'services'}
          className={tab === 'services' ? 'active' : ''}
          disabled={!!busy}
          onClick={() => setTab('services')}
        >
          服务配置
        </button>
        <button
          role="tab"
          aria-selected={tab === 'routing'}
          className={tab === 'routing' ? 'active' : ''}
          disabled={!!busy}
          onClick={() => {
            setAssignServiceId('')
            setTab('routing')
          }}
        >
          用途分配
        </button>
      </div>
      <ErrorNotice retry={resource.refresh}>{resource.error}</ErrorNotice>
      <EnvironmentServices
        resource={resource}
        busy={busy}
        setBusy={setBusy}
        notify={workspace.notify}
        handleError={handleError}
      />
      {tab === 'routing' ? (
        <>
          {assignServiceId && (
            <div className="model-next-step">
              <Check size={18} />
              <span>服务已保存，选择下方各功能使用的模型。</span>
              <button className="text-button" onClick={() => setTab('services')}>
                返回服务
              </button>
            </div>
          )}
          {assignServiceId && !services.some((service) => service.id === assignServiceId) ? (
            <p className="muted">正在更新可选模型…</p>
          ) : (
            <Routing
              services={services}
              initial={resource.data?.routing ?? null}
              refresh={resource.refresh}
            />
          )}
        </>
      ) : !draft ? (
        <ServiceList
          allServices={allServices}
          resource={resource}
          createService={createService}
          drafts={drafts}
          services={services}
          keys={keys}
          usesFor={usesFor}
          select={select}
        />
      ) : (
        <ServiceEditor
          busy={busy}
          select={select}
          dirty={dirty}
          draft={draft}
          setRemoveOpen={setRemoveOpen}
          update={update}
          setKeys={setKeys}
          connectionReady={connectionReady}
          error={error}
          conflict={conflict}
          save={save}
          setAssignServiceId={setAssignServiceId}
          setTab={setTab}
        >
          <ServiceConnectionFields
            draft={draft}
            busy={busy}
            changeAddress={changeAddress}
            update={update}
            keyValue={keys[draft.id] || ''}
            onKeyChange={(value) => {
              generationRef.current++
              setCheck(null)
              setCatalog(null)
              setKeys({ ...keys, [draft.id]: value })
            }}
          />
          <ServiceModelLibrary
            draft={draft}
            busy={busy}
            connectionReady={connectionReady}
            usesFor={usesFor}
            onAdd={(mode) => {
              if (mode === 'catalog') {
                setPicker('catalog')
                void request('models')
              } else {
                setError('')
                setPicker('manual')
              }
            }}
            onConfigure={(item) => {
              setActiveModel(item.id)
              setError('')
              setModelOpen(true)
            }}
            onTest={(item) => {
              setActiveModel(item.id)
              setTestPurpose(item.protocol === 'chat' ? 'assistant' : 'asr')
              setError('')
              setTestOpen(true)
            }}
          />
        </ServiceEditor>
      )}
      {picker && draft && (
        <ModelPicker
          picker={picker}
          draft={draft}
          busy={busy}
          setPicker={setPicker}
          addModels={addModels}
          error={error}
          catalog={catalog}
          setError={setError}
        />
      )}
      <ModelOptions
        modelOpen={modelOpen}
        model={model}
        draft={draft}
        setModelOpen={setModelOpen}
        busy={busy}
        updateModel={updateModel}
        automaticMatch={automaticMatch}
        setTestPurpose={setTestPurpose}
        setPreset={setPreset}
        setPresetJson={setPresetJson}
        update={update}
        setActiveModel={setActiveModel}
        error={error}
      />
      <ModelCheckResult checkOpen={checkOpen} check={check} setCheckOpen={setCheckOpen} />
      <RemoveServiceDialog
        removeOpen={removeOpen}
        draft={draft}
        busy={busy}
        setRemoveOpen={setRemoveOpen}
        error={error}
        remove={remove}
      />
      <ReasoningPresetEditor
        preset={preset}
        model={model}
        setPreset={setPreset}
        presetJson={presetJson}
        updateModel={updateModel}
        setError={setError}
        setPresetJson={setPresetJson}
        error={error}
      />
      <ModelTestDialog
        testOpen={testOpen}
        draft={draft}
        busy={busy}
        setTestOpen={setTestOpen}
        model={model}
        testPurpose={testPurpose}
        setTestPurpose={setTestPurpose}
        request={request}
      />
      <UnsavedKeysDialog
        blocker={blocker}
        busy={busy}
        keys={keys}
        save={save}
        drafts={drafts}
        services={services}
        setKeys={setKeys}
        error={error}
      />
    </div>
  )
}
