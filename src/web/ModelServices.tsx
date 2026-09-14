import { useEffect, useRef, useState } from 'react'
import { useBlocker } from 'react-router'
import { ArrowLeft, Check, ChevronRight, Cpu, Plus, Search, Trash2 } from 'lucide-react'
import type {
  CompanyModel,
  CompanyPreset,
  CompanyService,
  ModelCheck,
  ModelRouting,
  ModelSelection,
} from '../shared/company-contracts'
import { api, ApiError, dateLabel, useResource, write } from './api'
import { AutoTextarea, BusyButton, ConflictRecovery, ErrorNotice, Modal } from './ui'
import { useWorkspace } from './workspace'
import { cleanServiceDraft, newModel, validateCompanyParameters } from './model-service-drafts'
import type { ServiceDraft } from './model-service-drafts'

type Listing = { services: CompanyService[]; routing: ModelRouting }
type Purpose = 'assistant' | 'report' | 'asr'
const purposeNames = { assistant: '工作助手', report: '报告生成', asr: '语音转写' }
const protocolNames = {
  chat: '聊天 · Chat Completions',
  transcriptions: '语音 · 文件转写',
  'qwen-asr': '语音 · Qwen-ASR 兼容',
}

export function ModelServices() {
  const workspace = useWorkspace()
  const resource = useResource<Listing>('/settings/model-services')
  const [tab, setTab] = useState<'services' | 'routing'>('services')
  const [selected, setSelected] = useState<string | null>(null)
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [activeModel, setActiveModel] = useState('')
  const [catalog, setCatalog] = useState<{
    models: string[]
    source: string
    truncated: boolean
  } | null>(null)
  const [query, setQuery] = useState('')
  const [check, setCheck] = useState<ModelCheck | null>(null)
  const [testPurpose, setTestPurpose] = useState<Purpose>('assistant')
  const [testOpen, setTestOpen] = useState(false)
  const [removeOpen, setRemoveOpen] = useState(false)
  const [preset, setPreset] = useState<CompanyPreset | null>(null)
  const [presetJson, setPresetJson] = useState('{}')
  const drafts = (workspace.drafts.modelServices as Record<string, ServiceDraft>) || {}
  const services = resource.data?.services ?? []
  const draft = selected ? (drafts[selected] ?? services.find((s) => s.id === selected)) : undefined
  const model = draft?.models.find((m) => m.id === activeModel) ?? draft?.models[0]
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
    workspace.setDraft('modelServices', { ...drafts, [next.id]: cleanServiceDraft(next) })
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
  const capture = () => {
    if (!draft) throw new Error('请选择服务')
    for (const m of draft.models)
      for (const p of m.presets)
        validateCompanyParameters(
          p.mode === 'simple' ? { reasoning_effort: p.value } : p.parameters,
        )
    return {
      name: draft.name,
      baseUrl: draft.baseUrl,
      models: draft.models,
      expectedRevision: draft.revision,
      apiKey: keys[draft.id] || '',
    }
  }
  const handleError = (e: unknown) => {
    setError((e as Error).message)
    if (e instanceof ApiError && e.status === 409) setConflict(true)
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      setKeys({})
      generation.current++
      window.dispatchEvent(new Event('paa-session-expired'))
    }
  }
  const save = async (target = draft): Promise<boolean> => {
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
              models: target.models,
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
        next[saved.id] = cleanServiceDraft(saved)
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
        ...capture(),
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
      if ('checks' in value) setCheck(value)
      else setCatalog(value)
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
      </div>
      <div className="tabs" role="tablist" aria-label="模型管理页面">
        <button
          role="tab"
          aria-selected={tab === 'services'}
          className={tab === 'services' ? 'active' : ''}
          onClick={() => setTab('services')}
        >
          服务配置
        </button>
        <button
          role="tab"
          aria-selected={tab === 'routing'}
          className={tab === 'routing' ? 'active' : ''}
          onClick={() => setTab('routing')}
        >
          用途分配
        </button>
      </div>
      <ErrorNotice>{resource.error}</ErrorNotice>
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
        <Routing
          services={services}
          initial={resource.data?.routing ?? null}
          refresh={resource.refresh}
        />
      ) : (
        <div className={`model-workspace ${selected ? 'editing' : ''}`}>
          <aside className="model-service-list">
            <div className="model-list-heading">
              <strong>服务</strong>
              <button
                className="icon-button"
                aria-label="添加模型服务"
                onClick={() => {
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
                }}
              >
                <Plus size={17} />
              </button>
            </div>
            {!allServices.length && <p className="muted">添加第一家服务</p>}
            {allServices.map((service) => (
              <button
                key={service.id}
                className={selected === service.id ? 'selected' : ''}
                onClick={() => select(service.id)}
              >
                <Cpu size={17} />
                <span>
                  {drafts[service.id]?.name || service.name}
                  <small>{service.revision ? `${service.models.length} 个模型` : '未保存'}</small>
                </span>
                <ChevronRight size={14} />
              </button>
            ))}
          </aside>
          {!draft ? (
            <div className="model-placeholder">
              <Cpu size={28} />
              <h3>选择或添加模型服务</h3>
            </div>
          ) : (
            <section className="model-editor">
              <button className="model-mobile-back text-button" onClick={() => select(null)}>
                <ArrowLeft size={16} /> 服务列表
              </button>
              <div className="model-editor-heading">
                <div>
                  <h3>{draft.name || '新服务'}</h3>
                  <span className="muted">
                    {draft.revision ? `已保存版本 ${draft.revision}` : '尚未保存'} ·{' '}
                    {check ? '查看本次检测' : '未测试当前编辑'}
                  </span>
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
              </div>
              <fieldset disabled={!!busy}>
                <legend>连接</legend>
                <div className="field-grid connection-fields">
                  <label>
                    服务名称
                    <input
                      value={draft.name}
                      maxLength={80}
                      onChange={(e) => update({ ...draft, name: e.target.value })}
                    />
                  </label>
                  <label>
                    Base URL
                    <input
                      value={draft.baseUrl}
                      placeholder="https://api.example.com/v1"
                      maxLength={2048}
                      autoComplete="off"
                      onChange={(e) => update({ ...draft, baseUrl: e.target.value })}
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
              <div className="model-section-heading">
                <h3>模型</h3>
                <div className="card-actions">
                  <BusyButton
                    busy={busy === 'models'}
                    disabled={!!busy}
                    onClick={() => void request('models')}
                  >
                    <Search size={15} />
                    获取模型
                  </BusyButton>
                  <button
                    disabled={draft.models.length >= 32 || !!busy}
                    onClick={() => {
                      const next = newModel()
                      update({ ...draft, models: [...draft.models, next] })
                      setActiveModel(next.id)
                    }}
                  >
                    <Plus size={15} />
                    手动添加
                  </button>
                </div>
              </div>
              {catalog && (
                <div className="model-catalog">
                  <label>
                    搜索可用模型
                    <input value={query} onChange={(e) => setQuery(e.target.value)} />
                  </label>
                  <small className="wrap-anywhere">
                    目录：{catalog.source}
                    {catalog.truncated ? '（目录有更多条目，可手动填写）' : ''}
                  </small>
                  <div role="list" aria-label="可用模型目录">
                    {catalog.models
                      .filter((id) => id.toLowerCase().includes(query.toLowerCase()))
                      .map((id) => (
                        <button
                          key={id}
                          disabled={
                            draft.models.length >= 32 ||
                            draft.models.some((m) => m.model === id && m.protocol === 'chat')
                          }
                          onClick={() => {
                            const next = newModel(id)
                            update({ ...draft, models: [...draft.models, next] })
                            setActiveModel(next.id)
                          }}
                        >
                          <span>{id}</span>
                          <Plus size={14} />
                        </button>
                      ))}
                    {!catalog.models.length && <p>目录为空；已选模型保留，你也可以手动添加。</p>}
                  </div>
                </div>
              )}
              {!!draft.models.length && (
                <label>
                  当前模型
                  <select
                    value={model?.id}
                    onChange={(e) => {
                      generation.current++
                      setActiveModel(e.target.value)
                      setCheck(null)
                      setCatalog(null)
                    }}
                  >
                    {draft.models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.model || '未填写模型 ID'} · {protocolNames[m.protocol]}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {model && (
                <fieldset disabled={!!busy} className="model-options">
                  <legend>模型配置</legend>
                  <div className="field-grid">
                    <label>
                      模型 ID
                      <input
                        value={model.model}
                        maxLength={200}
                        onChange={(e) => updateModel({ ...model, model: e.target.value })}
                      />
                    </label>
                    <label>
                      接口协议
                      <select
                        value={model.protocol}
                        onChange={(e) => {
                          const protocol = e.target.value as CompanyModel['protocol']
                          updateModel({
                            ...model,
                            protocol,
                            presets: [],
                            selectedPresetId: null,
                            streaming: protocol === 'chat',
                          })
                          setTestPurpose(protocol === 'chat' ? 'assistant' : 'asr')
                        }}
                      >
                        {Object.entries(protocolNames).map(([id, name]) => (
                          <option key={id} value={id}>
                            {name}
                          </option>
                        ))}
                      </select>
                    </label>
                    {model.protocol === 'chat' ? (
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
                                  const p = model.presets.find(
                                    (p) => p.id === model.selectedPresetId,
                                  )!
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
                                    presets: model.presets.filter(
                                      (p) => p.id !== model.selectedPresetId,
                                    ),
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
                          placeholder="例如 zh"
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
                      }}
                    >
                      移除此模型配置
                    </button>
                  </div>
                </fieldset>
              )}
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
              <div className="model-savebar">
                <button
                  disabled={!model || !!busy}
                  onClick={() => {
                    setTestPurpose(model?.protocol === 'chat' ? 'assistant' : 'asr')
                    setTestOpen(true)
                  }}
                >
                  测试配置
                </button>
                <BusyButton
                  className="primary"
                  busy={busy === 'save'}
                  disabled={!!busy}
                  onClick={() => void save()}
                >
                  保存服务
                </BusyButton>
              </div>
              {check && (
                <section className="model-check">
                  <h3>本次检测</h3>
                  <p className="wrap-anywhere">
                    {check.service} · {check.model}
                  </p>
                  <small>
                    {dateLabel(check.time)} · {check.elapsedMs} ms · 草稿基于版本 {check.revision}
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
                      ? `用量：${JSON.stringify(check.usage)}`
                      : '服务未返回用量；费用未知。'}
                  </small>
                </section>
              )}
            </section>
          )}
        </div>
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
                setError((e as Error).message)
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
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  if (!value) return <p>正在读取用途…</p>
  const change = (purpose: Purpose, choice: ModelSelection | 'follow' | null) => {
    setDraft('modelRouting', { ...value, [purpose]: choice })
    setError('')
  }
  return (
    <section className="model-routing">
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
          <div className="panel routing-row" key={purpose}>
            <h3>{purposeNames[purpose]}</h3>
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
              {selected && typeof choice === 'object' && choice && (
                <>
                  <p className="wrap-anywhere">{selected.model.model}</p>
                  {purpose !== 'asr' && (
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
                          onChange={(e) =>
                            change(purpose, { ...choice, streaming: e.target.checked })
                          }
                        />
                        使用流式接口
                      </label>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        )
      })}
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
              setError((e as Error).message)
              setConflict(e instanceof ApiError && e.status === 409)
            } finally {
              setBusy(false)
            }
          }}
        >
          保存用途分配
        </BusyButton>
      </div>
    </section>
  )
}
