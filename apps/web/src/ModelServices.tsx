import { useEffect, useRef, useState } from 'react'
import { useBlocker } from 'react-router'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  Cpu,
  Plus,
  Search,
  SlidersHorizontal,
  Trash2,
  FlaskConical,
} from 'lucide-react'
import type {
  CompanyModel,
  CompanyPreset,
  CompanyService,
  ModelCheck,
  ModelRouting,
  ModelSelection,
} from '@paa/api-contracts'
import { api, ApiError, dateLabel, useResource, write } from './api'
import { AutoTextarea, BusyButton, ConflictRecovery, ErrorNotice, Modal, PanelSection } from './ui'
import { useWorkspace } from './workspace'
import {
  appendServiceModels,
  cleanServiceDraft,
  serviceHasChanges,
  validateCompanyParameters,
} from './model-service-drafts'
import type { ServiceDraft } from './model-service-drafts'
import {
  changeModelProtocol,
  detectServicePreset,
  matchModelProtocol,
  requireModelProtocols,
  resolveModelProtocol,
  servicePresets,
} from './model-service-presets'
import type { ServicePreset } from './model-service-presets'

type Listing = { services: CompanyService[]; routing: ModelRouting }
type Purpose = 'assistant' | 'report' | 'asr'
const purposeNames = { assistant: '工作助手', report: '报告生成', asr: '语音转写' }
const protocolNames = {
  chat: '聊天 · Chat Completions',
  transcriptions: '语音 · 文件转写',
  'qwen-asr': '语音 · Qwen-ASR 兼容',
  'dashscope-asr': '语音 · 阿里原生语音转写',
}

export function ModelServices() {
  const workspace = useWorkspace()
  const resource = useResource<Listing>('/settings/model-services')
  const [tab, setTab] = useState<'services' | 'routing'>('services')
  const [selected, setSelected] = useState<string | null>(null)
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<Error | string>('')
  const [conflict, setConflict] = useState(false)
  const [activeModel, setActiveModel] = useState('')
  const [catalog, setCatalog] = useState<{
    models: string[]
    source: string
    truncated: boolean
  } | null>(null)
  const [query, setQuery] = useState('')
  const [picker, setPicker] = useState<'catalog' | 'manual' | null>(null)
  const [pickedModels, setPickedModels] = useState<string[]>([])
  const [manualModel, setManualModel] = useState('')
  const [modelOpen, setModelOpen] = useState(false)
  const [checkOpen, setCheckOpen] = useState(false)
  const [assignServiceId, setAssignServiceId] = useState('')
  const [check, setCheck] = useState<ModelCheck | null>(null)
  const [testPurpose, setTestPurpose] = useState<Purpose>('assistant')
  const [testOpen, setTestOpen] = useState(false)
  const [removeOpen, setRemoveOpen] = useState(false)
  const [preset, setPreset] = useState<CompanyPreset | null>(null)
  const [presetJson, setPresetJson] = useState('{}')
  const drafts = (workspace.drafts.modelServices as Record<string, ServiceDraft>) || {}
  const services = resource.data?.services ?? []
  const draft: ServiceDraft | undefined = selected
    ? (drafts[selected] ?? services.find((s) => s.id === selected))
    : undefined
  const currentModel = draft?.models.find((m) => m.id === activeModel)
  const model =
    currentModel && draft ? resolveModelProtocol(draft.baseUrl, currentModel) : undefined
  const automaticMatch =
    model?.protocolMode === 'auto' && draft ? matchModelProtocol(draft.baseUrl, model.model) : null
  const savedService = services.find((service) => service.id === draft?.id)
  const dirty = !!draft && (serviceHasChanges(draft, savedService) || !!keys[draft.id])
  const connectionReady =
    !!draft?.name.trim() &&
    !!draft.baseUrl.trim() &&
    (!!keys[draft.id] || (draft.hasKey && draft.baseUrl === savedService?.baseUrl))
  const generation = useRef(0)
  const alive = useRef(true)
  const hasKeys = Object.values(keys).some(Boolean)
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      hasKeys && currentLocation.pathname !== nextLocation.pathname,
  )
  useEffect(() => {
    alive.current = true
    const epoch = generation
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
    generation.current++
    setCatalog(null)
    setCheck(null)
    setError('')
    setConflict(false)
    workspace.setDraft('modelServices', {
      ...drafts,
      [next.id]: cleanServiceDraft({
        ...next,
        models: next.models.map((m) => resolveModelProtocol(next.baseUrl, m)),
      }),
    })
  }
  const select = (id: string | null) => {
    generation.current++
    setSelected(id)
    setActiveModel('')
    setCatalog(null)
    setCheck(null)
    setError('')
    setConflict(false)
  }
  const updateModel = (next: CompanyModel) =>
    draft && update({ ...draft, models: draft.models.map((m) => (m.id === next.id ? next : m)) })
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
  const handleError = (e: unknown) => {
    setError(e as Error)
    if (e instanceof ApiError && e.status === 409) setConflict(true)
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      setKeys({})
      generation.current++
      window.dispatchEvent(new Event('paa-session-expired'))
    }
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
      const saved = await write<CompanyService>(
        target.revision ? `/settings/model-services/${target.id}` : '/settings/model-services',
        payload,
        target.revision ? 'PATCH' : 'POST',
      )
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
      generation.current++
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
  const request = async (kind: 'models' | 'test') => {
    if (!draft) return
    const requestGeneration = ++generation.current
    const version = crypto.randomUUID()
    setBusy(kind)
    setError('')
    setConflict(false)
    try {
      const value = await write<
        { models: string[]; source: string; truncated: boolean; draftVersion: string } | ModelCheck
      >(`/settings/model-services/${kind}`, {
        ...capture(kind === 'test'),
        serviceId: draft.revision ? draft.id : null,
        modelId: model?.id ?? null,
        purpose: testPurpose,
        draftVersion: version,
      })
      if (
        !alive.current ||
        requestGeneration !== generation.current ||
        value.draftVersion !== version
      )
        return
      if ('checks' in value) {
        setCheck(value)
        setCheckOpen(true)
      } else setCatalog(value)
    } catch (e) {
      if (alive.current && requestGeneration === generation.current) handleError(e)
    } finally {
      if (alive.current) setBusy('')
      setTestOpen(false)
    }
  }
  const remove = async () => {
    if (!draft) return
    setBusy('delete')
    try {
      if (draft.revision)
        await write(
          `/settings/model-services/${draft.id}`,
          { expectedRevision: draft.revision },
          'DELETE',
        )
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
  const allServices = [
    ...services,
    ...Object.values(drafts).filter((d) => !d.revision && !services.some((s) => s.id === d.id)),
  ]
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
      {resource.data?.routing.source === 'environment' && (
        <div className="notice model-environment">
          <details>
            <summary>当前使用服务器环境配置</summary>
            <p>
              助手：{resource.data.routing.environment?.assistant.model || '未设置'}；语音：
              {resource.data.routing.environment?.asr.model || '未设置'}。
            </p>
            <p className="wrap-anywhere">
              {resource.data.routing.environment?.assistant.baseUrl || '助手地址未设置'}
            </p>
            <p className="wrap-anywhere">
              {resource.data.routing.environment?.asr.baseUrl || '语音地址未设置'}
            </p>
          </details>
          <BusyButton
            busy={busy === 'import'}
            onClick={async () => {
              if (
                !window.confirm(
                  '导入当前环境服务并交由本页面管理？未配置的用途仍保留为空，此操作不会发起模型调用。',
                )
              )
                return
              setBusy('import')
              try {
                await write('/settings/model-services/import-environment', {})
                resource.refresh()
                workspace.notify('环境配置已导入')
              } catch (e) {
                handleError(e)
              } finally {
                setBusy('')
              }
            }}
          >
            导入配置
          </BusyButton>
        </div>
      )}
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
        <section className="sectioned-panel service-overview" aria-label="模型服务列表">
          <header className="service-overview-heading">
            <h3>
              已添加的服务 <span className="muted">{allServices.length}</span>
            </h3>
            <span className="muted">选择服务管理连接与模型</span>
          </header>
          {!resource.data && !resource.error && <p className="model-placeholder">正在读取服务…</p>}
          {resource.data && !allServices.length && (
            <div className="model-placeholder">
              <Cpu size={32} />
              <h3>添加你的第一个模型服务</h3>
              <p>填写服务地址和密钥，添加模型后分配给各项功能。</p>
              <button className="primary" onClick={createService}>
                <Plus size={16} /> 添加服务
              </button>
            </div>
          )}
          {allServices.map((service) => {
            const current = drafts[service.id] ?? service
            const changed =
              serviceHasChanges(
                current,
                services.find((item) => item.id === service.id),
              ) || !!keys[service.id]
            const purposes = usesFor(service.id)
            return (
              <button
                className="service-overview-row"
                key={service.id}
                onClick={() => select(service.id)}
              >
                <span className="service-symbol">
                  <Cpu size={21} />
                </span>
                <span className="service-overview-name">
                  <strong>{current.name || '新服务'}</strong>
                  <small>{current.baseUrl || '待填写连接信息'}</small>
                </span>
                <span className="service-overview-meta">
                  <span>
                    {current.models.length} 个模型{changed ? ' · 未保存' : ''}
                  </span>
                  <small>{purposes.length ? purposes.join(' · ') : '未分配用途'}</small>
                </span>
                <ChevronRight size={17} />
              </button>
            )
          })}
        </section>
      ) : (
        <div className="service-detail">
          <div className="service-detail-toolbar">
            <button className="text-button" disabled={!!busy} onClick={() => select(null)}>
              <ArrowLeft size={16} /> 全部服务
            </button>
            <span className={`service-save-state${dirty ? ' changed' : ''}`}>
              {dirty ? '有未保存的更改' : '已保存'}
            </span>
          </div>
          <section className="sectioned-panel model-editor" key={draft.id}>
            <header className="model-editor-heading">
              <div>
                <h3>{draft.name || '新服务'}</h3>
                <span className="muted">{draft.models.length} 个模型</span>
              </div>
              <button
                className="icon-button danger"
                aria-label={draft.revision ? '删除当前模型服务' : '丢弃草稿'}
                title={draft.revision ? '删除当前模型服务' : '丢弃草稿'}
                disabled={!!busy}
                onClick={() => setRemoveOpen(true)}
              >
                <Trash2 size={17} />
              </button>
            </header>
            <PanelSection
              title="连接信息"
              status={draft.baseUrl || '待填写'}
              defaultOpen={!draft.revision}
            >
              <fieldset disabled={!!busy} aria-label="连接信息">
                <div className="field-grid connection-fields">
                  <label>
                    服务商预设
                    <select
                      value={draft.providerPreset ?? detectServicePreset(draft.baseUrl)}
                      onChange={(e) => {
                        const id = e.target.value as ServicePreset
                        const preset = servicePresets[id]
                        const defaultName =
                          draft.name === '新服务' ||
                          Object.values(servicePresets).some((p) => p.name === draft.name)
                        changeAddress(
                          id === 'custom' ? draft.baseUrl : preset.baseUrl,
                          id,
                          id !== 'custom' && defaultName ? preset.name : draft.name,
                        )
                      }}
                    >
                      {Object.entries(servicePresets).map(([id, preset]) => (
                        <option key={id} value={id}>
                          {preset.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    服务名称
                    <input
                      value={draft.name}
                      maxLength={80}
                      onChange={(e) => update({ ...draft, name: e.target.value })}
                    />
                  </label>
                  <label className="full-field">
                    Base URL
                    <input
                      value={draft.baseUrl}
                      placeholder="https://api.example.com/v1"
                      maxLength={2048}
                      autoComplete="off"
                      onChange={(e) =>
                        changeAddress(e.target.value, detectServicePreset(e.target.value))
                      }
                    />
                  </label>
                  <label className="full-field">
                    API 密钥{' '}
                    <span className="muted">
                      {draft.hasKey ? '已设置；地址不变时留空保留' : '尚未设置'}
                    </span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={keys[draft.id] || ''}
                      maxLength={4096}
                      placeholder={draft.hasKey ? '输入新密钥以替换' : '输入密钥'}
                      onChange={(e) => {
                        generation.current++
                        setCheck(null)
                        setCatalog(null)
                        setKeys({ ...keys, [draft.id]: e.target.value })
                      }}
                    />
                  </label>
                </div>
              </fieldset>
            </PanelSection>
            <PanelSection title="可用模型" status={`${draft.models.length} / 32`} defaultOpen>
              <div className="model-library-toolbar">
                <span className="muted">选择模型进行设置或测试</span>
                <div className="card-actions">
                  <BusyButton
                    busy={busy === 'models'}
                    disabled={!!busy || !connectionReady}
                    onClick={() => {
                      setQuery('')
                      setPickedModels([])
                      setPicker('catalog')
                      void request('models')
                    }}
                  >
                    <Search size={15} /> 获取模型
                  </BusyButton>
                  <button
                    disabled={draft.models.length >= 32 || !!busy}
                    onClick={() => {
                      setManualModel('')
                      setError('')
                      setPicker('manual')
                    }}
                  >
                    <Plus size={15} /> 手动添加
                  </button>
                </div>
              </div>
              {!draft.models.length && (
                <div className="model-library-empty">
                  <Cpu size={24} />
                  <p>还没有添加模型</p>
                  <small>
                    {connectionReady
                      ? '获取服务提供的模型列表，或手动输入模型 ID。'
                      : '先填写服务地址和密钥，也可以手动添加模型。'}
                  </small>
                </div>
              )}
              <div className="model-library" role="list" aria-label="已添加模型">
                {draft.models.map((item) => {
                  const unresolved =
                    item.protocolMode === 'auto' &&
                    !matchModelProtocol(draft.baseUrl, item.model).protocol
                  const purposes = usesFor(draft.id, item.id)
                  return (
                    <div className="model-library-row" role="listitem" key={item.id}>
                      <div className="model-library-info">
                        <strong>{item.model || '未填写模型 ID'}</strong>
                        <small className={unresolved ? 'error-text' : ''}>
                          {unresolved
                            ? '需要选择接口协议'
                            : item.protocol === 'chat'
                              ? '聊天模型'
                              : '语音转写'}
                          {purposes.length ? ` · ${purposes.join('、')}` : ''}
                        </small>
                      </div>
                      <div className="card-actions">
                        <button
                          disabled={!!busy}
                          aria-label={`设置 ${item.model}`}
                          onClick={() => {
                            setActiveModel(item.id)
                            setError('')
                            setModelOpen(true)
                          }}
                        >
                          <SlidersHorizontal size={15} /> 设置
                        </button>
                        <button
                          disabled={!!busy || !connectionReady || unresolved}
                          aria-label={`测试 ${item.model}`}
                          onClick={() => {
                            setActiveModel(item.id)
                            setTestPurpose(item.protocol === 'chat' ? 'assistant' : 'asr')
                            setError('')
                            setTestOpen(true)
                          }}
                        >
                          <FlaskConical size={15} /> 测试
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </PanelSection>
            <div className="model-editor-feedback">
              <ErrorNotice>{error}</ErrorNotice>
              {conflict && draft.revision > 0 && (
                <ConflictRecovery
                  load={() => api<CompanyService>(`/settings/model-services/${draft.id}`)}
                  render={(latest) => (
                    <p>
                      {latest.name} · 版本 {latest.revision}
                    </p>
                  )}
                  keep={(latest) =>
                    update({ ...draft, revision: latest.revision, hasKey: latest.hasKey })
                  }
                  replace={(latest) => {
                    update(cleanServiceDraft(latest))
                    setKeys((previous) => ({ ...previous, [draft.id]: '' }))
                  }}
                />
              )}
            </div>
            <footer className="model-savebar">
              <span className="muted">
                {dirty
                  ? '保存后生效'
                  : draft.models.length
                    ? '选择各项功能使用的模型'
                    : '添加模型后可设置用途'}
              </span>
              <button disabled={!!busy || !connectionReady} onClick={() => void save()}>
                保存服务
              </button>
              <BusyButton
                className="primary"
                busy={busy === 'save'}
                disabled={!!busy || !connectionReady || !draft.models.length}
                onClick={() => {
                  if (dirty) void save(draft, true)
                  else {
                    setAssignServiceId('')
                    setTab('routing')
                  }
                }}
              >
                {dirty ? '保存并设置用途' : '设置用途'} <ArrowRight size={15} />
              </BusyButton>
            </footer>
          </section>
        </div>
      )}
      {picker && draft && (
        <Modal
          title={picker === 'catalog' ? '添加可用模型' : '手动添加模型'}
          className="model-picker-dialog"
          onClose={() => {
            if (!busy) setPicker(null)
          }}
        >
          {picker === 'manual' ? (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                addModels([manualModel])
              }}
            >
              <label>
                模型 ID
                <input
                  autoFocus
                  required
                  maxLength={200}
                  placeholder="例如 qwen-plus"
                  value={manualModel}
                  onChange={(event) => setManualModel(event.target.value)}
                />
              </label>
              <ErrorNotice>{error}</ErrorNotice>
              <div className="form-actions">
                <button type="button" onClick={() => setPicker(null)}>
                  取消
                </button>
                <button className="primary" disabled={!manualModel.trim()}>
                  添加模型
                </button>
              </div>
            </form>
          ) : (
            <>
              {busy === 'models' && <p role="status">正在获取模型列表…</p>}
              <ErrorNotice>{error}</ErrorNotice>
              {catalog && (
                <>
                  <label className="model-picker-search">
                    <Search size={16} />
                    <input
                      aria-label="搜索可用模型"
                      placeholder="搜索模型 ID"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                    />
                  </label>
                  <div className="model-picker-list" aria-label="可用模型目录">
                    {catalog.models
                      .filter((id) => id.toLowerCase().includes(query.toLowerCase()))
                      .map((id) => {
                        const added = draft.models.some((item) => item.model === id)
                        const checked = pickedModels.includes(id)
                        return (
                          <label key={id}>
                            <input
                              type="checkbox"
                              checked={added || checked}
                              disabled={
                                added ||
                                (!checked && pickedModels.length + draft.models.length >= 32)
                              }
                              onChange={(event) =>
                                setPickedModels((previous) =>
                                  event.target.checked
                                    ? [...previous, id]
                                    : previous.filter((value) => value !== id),
                                )
                              }
                            />
                            <span>{id}</span>
                            {added && <small>已添加</small>}
                          </label>
                        )
                      })}
                    {!catalog.models.some((id) =>
                      id.toLowerCase().includes(query.toLowerCase()),
                    ) && <p className="muted">没有找到匹配的模型，可手动添加。</p>}
                  </div>
                  {catalog.truncated && (
                    <small className="muted">列表未完全返回，可手动输入其它模型 ID。</small>
                  )}
                </>
              )}
              <div className="form-actions model-picker-actions">
                <span className="muted">已选 {pickedModels.length} 个</span>
                <button
                  disabled={!!busy}
                  onClick={() => {
                    setManualModel(query)
                    setError('')
                    setPicker('manual')
                  }}
                >
                  手动输入
                </button>
                <button
                  className="primary"
                  disabled={!!busy || !pickedModels.length}
                  onClick={() => addModels(pickedModels)}
                >
                  添加所选模型
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
      {modelOpen && model && draft && (
        <Modal
          title={`设置 ${model.model || '模型'}`}
          className="model-settings-dialog"
          onClose={() => setModelOpen(false)}
        >
          <fieldset disabled={!!busy} className="model-options" aria-label="模型配置">
            <div className="field-grid">
              <label>
                模型 ID
                <input
                  value={model.model}
                  maxLength={200}
                  onChange={(e) => updateModel({ ...model, model: e.target.value })}
                />
              </label>
              <div className="model-protocol-status" role="status">
                {automaticMatch && !automaticMatch.protocol
                  ? model.model
                    ? automaticMatch.reason
                    : '填写模型 ID 后自动匹配接口。'
                  : `${automaticMatch ? '已自动匹配' : '当前接口'}：${protocolNames[model.protocol]}`}
              </div>
              <details
                className="model-advanced full-field"
                key={model.id}
                open={!!automaticMatch && !automaticMatch.protocol}
              >
                <summary>接口与高级设置</summary>
                <label>
                  接口协议
                  <select
                    value={model.protocolMode === 'auto' ? 'auto' : model.protocol}
                    onChange={(e) => {
                      if (e.target.value === 'auto') {
                        updateModel({ ...model, protocolMode: 'auto' })
                      } else {
                        const protocol = e.target.value as CompanyModel['protocol']
                        updateModel({
                          ...changeModelProtocol(model, protocol),
                          protocolMode: 'manual',
                        })
                        setTestPurpose(protocol === 'chat' ? 'assistant' : 'asr')
                      }
                    }}
                  >
                    <option value="auto">自动匹配</option>
                    {Object.entries(protocolNames).map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
              </details>
              {automaticMatch && !automaticMatch.protocol ? null : model.protocol === 'chat' ? (
                <>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={model.streaming}
                      onChange={(e) => updateModel({ ...model, streaming: e.target.checked })}
                    />
                    使用流式接口
                  </label>
                  <label>
                    推理预设
                    <select
                      value={model.selectedPresetId || ''}
                      onChange={(e) =>
                        updateModel({ ...model, selectedPresetId: e.target.value || null })
                      }
                    >
                      <option value="">服务默认</option>
                      {model.presets.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="card-actions full-field">
                    <button
                      disabled={model.presets.length >= 16}
                      onClick={() => {
                        setPreset({
                          id: crypto.randomUUID(),
                          name: '',
                          mode: 'simple',
                          value: '',
                          parameters: {},
                        })
                        setPresetJson('{}')
                      }}
                    >
                      添加预设
                    </button>
                    {model.selectedPresetId && (
                      <>
                        <button
                          onClick={() => {
                            const p = model.presets.find((p) => p.id === model.selectedPresetId)!
                            setPreset(structuredClone(p))
                            setPresetJson(JSON.stringify(p.parameters, null, 2))
                          }}
                        >
                          编辑预设
                        </button>
                        <button
                          onClick={() =>
                            updateModel({
                              ...model,
                              presets: model.presets.filter((p) => p.id !== model.selectedPresetId),
                              selectedPresetId: null,
                            })
                          }
                        >
                          删除预设
                        </button>
                      </>
                    )}
                  </div>
                </>
              ) : (
                <label>
                  识别语言（可选）
                  <input
                    value={model.language}
                    disabled={model.protocol === 'dashscope-asr'}
                    placeholder={model.protocol === 'dashscope-asr' ? '自动识别' : '例如 zh'}
                    maxLength={20}
                    onChange={(e) => updateModel({ ...model, language: e.target.value })}
                  />
                </label>
              )}
              <button
                className="text-button danger full-field"
                onClick={() => {
                  update({ ...draft, models: draft.models.filter((m) => m.id !== model.id) })
                  setActiveModel('')
                  setModelOpen(false)
                }}
              >
                移除此模型配置
              </button>
            </div>
          </fieldset>
          <ErrorNotice>{error}</ErrorNotice>
          <div className="form-actions">
            <span className="muted">完成后记得保存服务</span>
            <button className="primary" onClick={() => setModelOpen(false)}>
              完成
            </button>
          </div>
        </Modal>
      )}
      {checkOpen && check && (
        <Modal title="模型测试结果" onClose={() => setCheckOpen(false)}>
          <section className="model-check">
            <p className="wrap-anywhere">
              {check.service} · {check.model}
            </p>
            <small>
              {dateLabel(check.time)} · {check.elapsedMs} ms
            </small>
            {check.checks.map((item) => (
              <p key={item.name} className={item.state === 'failed' ? 'error-text' : ''}>
                {item.state === 'passed' ? <Check size={15} /> : null} {item.name}：
                {{ passed: '通过', failed: '失败', untested: '未测试' }[item.state]}
                {item.message && `，${item.message}`}
              </p>
            ))}
            <small>
              {check.usage
                ? Object.entries(check.usage)
                    .map(([name, count]) => `${name}：${count}`)
                    .join(' · ')
                : '服务未返回用量。'}
            </small>
          </section>
          <div className="form-actions">
            <button onClick={() => setCheckOpen(false)}>关闭</button>
          </div>
        </Modal>
      )}
      {removeOpen && draft && (
        <Modal
          title={draft.revision ? '删除模型服务' : '丢弃服务草稿'}
          onClose={() => {
            if (!busy) setRemoveOpen(false)
          }}
        >
          <p>
            {draft.revision
              ? '删除后，旧任务将无法继续使用这个服务，历史工作和报告会保留。'
              : '丢弃后，这份服务草稿和其中尚未保存的密钥将被清除。'}
          </p>
          <ErrorNotice>{error}</ErrorNotice>
          <div className="form-actions">
            <button disabled={!!busy} onClick={() => setRemoveOpen(false)}>
              继续编辑
            </button>
            <BusyButton
              className="danger"
              busy={busy === 'delete'}
              disabled={!!busy}
              onClick={() => void remove()}
            >
              {draft.revision ? '确认删除服务' : '丢弃草稿'}
            </BusyButton>
          </div>
        </Modal>
      )}
      {preset && model && (
        <Modal title="推理预设" onClose={() => setPreset(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              try {
                const value =
                  preset.mode === 'advanced'
                    ? validateCompanyParameters(JSON.parse(presetJson))
                    : validateCompanyParameters({ reasoning_effort: preset.value })
                const next = { ...preset, parameters: preset.mode === 'advanced' ? value : {} }
                updateModel({
                  ...model,
                  presets: [...model.presets.filter((p) => p.id !== preset.id), next],
                  selectedPresetId: preset.id,
                })
                setPreset(null)
              } catch (e) {
                setError(e as Error)
              }
            }}
          >
            <label>
              预设名称
              <input
                value={preset.name}
                required
                maxLength={80}
                onChange={(e) => setPreset({ ...preset, name: e.target.value })}
              />
            </label>
            <label>
              设置方式
              <select
                value={preset.mode}
                onChange={(e) =>
                  setPreset({ ...preset, mode: e.target.value as CompanyPreset['mode'] })
                }
              >
                <option value="simple">推理强度字符串</option>
                <option value="advanced">高级 JSON 参数</option>
              </select>
            </label>
            {preset.mode === 'simple' ? (
              <label>
                推理强度
                <input
                  value={preset.value}
                  required
                  maxLength={512}
                  placeholder="例如 high"
                  onChange={(e) => setPreset({ ...preset, value: e.target.value })}
                />
              </label>
            ) : (
              <details open>
                <summary>高级参数</summary>
                <label>
                  JSON 参数
                  <AutoTextarea
                    rows={3}
                    value={presetJson}
                    onChange={(e) => setPresetJson(e.target.value)}
                  />
                </label>
              </details>
            )}
            <ErrorNotice>{error}</ErrorNotice>
            <div className="form-actions">
              <button type="button" onClick={() => setPreset(null)}>
                取消
              </button>
              <button className="primary" type="submit">
                保存预设到草稿
              </button>
            </div>
          </form>
        </Modal>
      )}
      {testOpen && draft && (
        <Modal
          title="测试模型配置"
          onClose={() => {
            if (!busy) setTestOpen(false)
          }}
        >
          <p className="wrap-anywhere">
            接收服务：{draft.name}（{draft.baseUrl}）
          </p>
          <p className="wrap-anywhere">模型：{model?.model || '未填写'}</p>
          <label>
            检测用途
            <select
              disabled={!!busy}
              value={testPurpose}
              onChange={(e) => setTestPurpose(e.target.value as Purpose)}
            >
              {(model?.protocol === 'chat' ? ['assistant', 'report'] : ['asr']).map((p) => (
                <option key={p} value={p}>
                  {purposeNames[p as Purpose]}
                </option>
              ))}
            </select>
          </label>
          <p>
            会发送固定的
            {testPurpose === 'asr'
              ? '中文短语音'
              : testPurpose === 'assistant'
                ? '文字、图片与工具测试样本'
                : '文字与工具测试样本'}
            ，可能产生服务费用，不使用员工资料。
          </p>
          <div className="form-actions">
            <button disabled={!!busy} onClick={() => setTestOpen(false)}>
              取消
            </button>
            <BusyButton
              className="primary"
              busy={busy === 'test'}
              disabled={!!busy}
              onClick={() => void request('test')}
            >
              开始测试
            </BusyButton>
          </div>
        </Modal>
      )}
      {blocker.state === 'blocked' && (
        <Modal title="密钥尚未保存" onClose={() => blocker.reset()}>
          <p>离开会丢弃尚未保存的密钥，普通编辑草稿仍保留。</p>
          <div className="card-actions">
            <BusyButton
              busy={busy === 'save'}
              onClick={async () => {
                for (const id of Object.keys(keys).filter((id) => keys[id])) {
                  if (!(await save(drafts[id] ?? services.find((s) => s.id === id)))) return
                }
                blocker.proceed()
              }}
            >
              保存后离开
            </BusyButton>
            <button
              onClick={() => {
                setKeys({})
                blocker.proceed()
              }}
            >
              丢弃密钥并离开
            </button>
            <button onClick={() => blocker.reset()}>继续编辑</button>
          </div>
          <ErrorNotice>{error}</ErrorNotice>
        </Modal>
      )}
    </div>
  )
}

function Routing({
  services,
  initial,
  refresh,
}: {
  services: CompanyService[]
  initial: ModelRouting | null
  refresh: () => void
}) {
  const { drafts, setDraft, notify } = useWorkspace()
  const value = (drafts.modelRouting as ModelRouting) || initial
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [conflict, setConflict] = useState(false)
  if (!value) return <p>正在读取用途…</p>
  const change = (purpose: Purpose, choice: ModelSelection | 'follow' | null) => {
    setDraft('modelRouting', { ...value, [purpose]: choice })
    setError('')
  }
  return (
    <section className="sectioned-panel model-routing">
      {(['assistant', 'report', 'asr'] as const).map((purpose) => {
        const choice = value[purpose]
        const options = services.flatMap((service) =>
          service.models
            .filter((m) => (purpose === 'asr' ? m.protocol !== 'chat' : m.protocol === 'chat'))
            .map((model) => ({ service, model })),
        )
        const selected =
          typeof choice === 'object' && choice
            ? options.find(
                (x) => x.service.id === choice.serviceId && x.model.id === choice.modelId,
              )
            : null
        return (
          <PanelSection
            key={purpose}
            title={purposeNames[purpose]}
            status={
              choice === 'follow'
                ? '同工作助手'
                : selected
                  ? `${selected.service.name} · ${selected.model.model}`
                  : '未配置'
            }
            defaultOpen={purpose === 'assistant'}
          >
            <div className="routing-fields">
              <label>
                使用的模型
                <select
                  value={
                    choice === 'follow'
                      ? 'follow'
                      : choice
                        ? `${choice.serviceId}/${choice.modelId}`
                        : ''
                  }
                  onChange={(e) => {
                    const option = options.find(
                      (x) => `${x.service.id}/${x.model.id}` === e.target.value,
                    )
                    change(
                      purpose,
                      e.target.value === 'follow'
                        ? 'follow'
                        : option
                          ? {
                              serviceId: option.service.id,
                              modelId: option.model.id,
                              presetId: option.model.selectedPresetId,
                              streaming: option.model.streaming,
                            }
                          : null,
                    )
                  }}
                >
                  <option value="">未配置</option>
                  {purpose === 'report' && <option value="follow">同工作助手</option>}
                  {options.map(({ service, model }) => (
                    <option key={`${service.id}/${model.id}`} value={`${service.id}/${model.id}`}>
                      {service.name} · {model.model}
                    </option>
                  ))}
                </select>
              </label>
              {choice === 'follow' && (
                <p className="muted">使用工作助手当前分配的模型、推理预设和请求方式。</p>
              )}
              {selected && typeof choice === 'object' && choice && purpose !== 'asr' && (
                <>
                  <label>
                    推理预设
                    <select
                      value={choice.presetId || ''}
                      onChange={(e) =>
                        change(purpose, { ...choice, presetId: e.target.value || null })
                      }
                    >
                      <option value="">服务默认</option>
                      {selected.model.presets.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={choice.streaming}
                      onChange={(e) => change(purpose, { ...choice, streaming: e.target.checked })}
                    />
                    使用流式接口
                  </label>
                </>
              )}
            </div>
          </PanelSection>
        )
      })}
      <div className="panel-footer">
        <ErrorNotice>{error}</ErrorNotice>
        {conflict && (
          <ConflictRecovery
            load={() => api<ModelRouting>('/settings/model-routing')}
            render={(latest) => <p>服务端用途版本 {latest.revision}</p>}
            keep={(latest) => {
              setDraft('modelRouting', { ...value, revision: latest.revision })
              setConflict(false)
            }}
            replace={(latest) => {
              setDraft('modelRouting', latest)
              setConflict(false)
            }}
          />
        )}
        <div className="form-actions editor-actions">
          <BusyButton
            className="primary"
            busy={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await write(
                  '/settings/model-routing',
                  {
                    assistant: value.assistant,
                    report: value.report,
                    asr: value.asr,
                    expectedRevision: value.revision,
                  },
                  'PUT',
                )
                setDraft('modelRouting', undefined)
                refresh()
                notify('用途分配已保存')
              } catch (e) {
                setError(e as Error)
                setConflict(e instanceof ApiError && e.status === 409)
              } finally {
                setBusy(false)
              }
            }}
          >
            保存用途分配
          </BusyButton>
        </div>
      </div>
    </section>
  )
}
