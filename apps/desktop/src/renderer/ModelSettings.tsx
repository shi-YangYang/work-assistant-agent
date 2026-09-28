import { useId, type Dispatch, type SetStateAction } from 'react'
import type { ServiceList } from '../shared/summary-contracts'
import { useModelSettings, useModelServiceEditor } from './useModelSettings'

export function ApiModelSettings({ visible }: { visible: boolean }): React.JSX.Element {
  const {
    list,
    setList,
    selected,
    opened,
    setOpened,
    error,
    automaticBusy,
    select,
    active,
    profiles,
    setAutomatic,
  } = useModelSettings(visible)
  return (
    <section className="api-settings" aria-label="模型服务管理">
      <div className="service-overview">
        <p>
          当前用于纪要：<strong>{active ? `${active.name} · ${active.model}` : '尚未选择'}</strong>
        </p>
        <label className="check-label">
          <input
            type="checkbox"
            checked={list.autoGenerate}
            disabled={automaticBusy}
            onChange={(event) => void setAutomatic(event.target.checked)}
          />
          转写完成后自动生成纪要{automaticBusy ? ' · 正在保存…' : ''}
        </label>
      </div>
      {error && (
        <p role="alert" className="audio-warning">
          {error}
        </p>
      )}
      <div className="service-layout">
        <aside className="service-list" aria-label="服务列表">
          <div className="section-heading">
            <h2>服务</h2>
            <button className="text-button" onClick={() => select(crypto.randomUUID())}>
              添加服务
            </button>
          </div>
          {profiles.map((profile) => (
            <button
              key={profile.id}
              className={`service-item ${profile.id === selected ? 'selected' : ''}`}
              aria-label={`${profile.name}${profile.id === list.activeProfileId ? ' · 使用中' : ''}`}
              aria-pressed={profile.id === selected}
              onClick={() => select(profile.id)}
            >
              <strong>
                {profile.name}
                {profile.id === list.activeProfileId ? ' · 使用中' : ''}
              </strong>
              <small>{profile.model || '连接与模型待配置'}</small>
            </button>
          ))}
          <p className="draft-hint">切换服务或页面会保留未保存的编辑，关闭应用前请保存。</p>
        </aside>
        <div className="service-editors">
          {opened.map((id) => (
            <div key={id} hidden={id !== selected}>
              <ServiceEditor
                id={id}
                list={list}
                setList={setList}
                onRemove={() => {
                  setOpened((previous) => previous.filter((item) => item !== id))
                  const next =
                    list.profiles.find((profile) => profile.id !== id)?.id || crypto.randomUUID()
                  select(next)
                }}
              />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
function ServiceEditor({
  id,
  list,
  setList,
  onRemove,
}: {
  id: string
  list: ServiceList
  setList: Dispatch<SetStateAction<ServiceList>>
  onRemove: () => void
}): React.JSX.Element {
  const panelId = useId()
  const {
    draft,
    setDraft,
    tab,
    setTab,
    hasKey,
    setHasKey,
    setSavedDraft,
    error,
    notice,
    busy,
    loading,
    network,
    directory,
    updatedAt,
    search,
    setSearch,
    check,
    editing,
    setEditing,
    presetName,
    setPresetName,
    presetMode,
    setPresetMode,
    presetValue,
    setPresetValue,
    change,
    load,
    mutate,
    run,
    entry,
    updatePresets,
    editPreset,
    applyPreset,
    knownNontext,
    saved,
    hasUnsavedChanges,
    recipient,
  } = useModelServiceEditor(id, list, setList)
  return (
    <section className="service-editor settings-card" aria-label="服务编辑">
      <div className="section-heading">
        <h2>{draft.name || '新服务'}</h2>
        <span className="draft-status">
          {loading
            ? '正在读取…'
            : busy
              ? '正在保存…'
              : hasUnsavedChanges || editing
                ? '有未保存的编辑'
                : '已保存'}
        </span>
      </div>
      <div
        className="tabs"
        role="tablist"
        aria-label="服务配置"
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault()
            const next = tab === 'connection' ? 'model' : 'connection'
            setTab(next)
            event.currentTarget
              .querySelector<HTMLButtonElement>(`[data-service-tab="${next}"]`)
              ?.focus()
          }
        }}
      >
        <button
          role="tab"
          data-service-tab="connection"
          id={`${panelId}-connection-tab`}
          aria-controls={`${panelId}-connection`}
          aria-selected={tab === 'connection'}
          tabIndex={tab === 'connection' ? 0 : -1}
          onClick={() => setTab('connection')}
        >
          连接配置
        </button>
        <button
          role="tab"
          data-service-tab="model"
          id={`${panelId}-model-tab`}
          aria-controls={`${panelId}-model`}
          aria-selected={tab === 'model'}
          tabIndex={tab === 'model' ? 0 : -1}
          onClick={() => setTab('model')}
        >
          模型与推理
        </button>
      </div>
      <fieldset disabled={busy || loading} className="service-form">
        <div
          hidden={tab !== 'connection'}
          className="service-tab"
          role="tabpanel"
          id={`${panelId}-connection`}
          aria-labelledby={`${panelId}-connection-tab`}
        >
          <label>
            服务名称
            <input
              value={draft.name}
              maxLength={80}
              onChange={(event) => change({ name: event.target.value })}
            />
          </label>
          <label>
            API Base URL
            <input
              value={draft.baseUrl}
              maxLength={2048}
              placeholder="https://example.com/v1"
              onChange={(event) => {
                change({ baseUrl: event.target.value, apiKey: '' }, true)
                setHasKey(false)
              }}
            />
          </label>
          <label>
            API 密钥
            <input
              type="password"
              autoComplete="off"
              value={draft.apiKey}
              maxLength={4096}
              placeholder={hasKey ? '已保存，留空保留' : '输入密钥'}
              onChange={(event) => change({ apiKey: event.target.value }, true)}
            />
          </label>
        </div>
        <div
          hidden={tab !== 'model'}
          className="service-tab"
          role="tabpanel"
          id={`${panelId}-model`}
          aria-labelledby={`${panelId}-model-tab`}
        >
          <div className="button-row">
            <button
              className="secondary-button"
              disabled={!!network}
              onClick={() => void run('models')}
            >
              获取模型
            </button>
            {updatedAt && <small>更新于 {new Date(updatedAt * 1000).toLocaleTimeString()}</small>}
          </div>
          {directory !== null && (
            <div className="model-directory">
              <label>
                搜索模型
                <input value={search} onChange={(event) => setSearch(event.target.value)} />
              </label>
              <label>
                可用模型列表
                <select
                  size={Math.min(6, Math.max(2, directory.length))}
                  value={directory.some((item) => item.id === draft.model) ? draft.model : ''}
                  onChange={(event) => change({ model: event.target.value })}
                >
                  <option value="" disabled>
                    选择模型
                  </option>
                  {directory
                    .filter((item) => item.id.toLowerCase().includes(search.toLowerCase()))
                    .map((item) => (
                      <option key={item.id} value={item.id} disabled={!item.selectable}>
                        {item.id}
                        {item.selectable ? '' : ' · 非文本模型'}
                      </option>
                    ))}
                </select>
              </label>
              {!directory.length && <p>没有返回模型，可手动填写模型 ID。</p>}
              {draft.model && !directory.some((item) => item.id === draft.model) && (
                <p>当前模型未出现在目录中，保留为手动 ID。</p>
              )}
            </div>
          )}
          <label>
            模型 ID
            <input
              value={draft.model}
              maxLength={256}
              placeholder="选择模型或手动填写"
              onChange={(event) => change({ model: event.target.value })}
            />
          </label>
          {knownNontext && (
            <p role="alert">
              此模型在该服务目录中明确为非文本模型，不能用于纪要；请选择其他模型或刷新目录。
            </p>
          )}
          <label>
            推理预设
            <select
              className="reasoning-preset-select"
              aria-label="推理预设"
              value={entry.selectedPresetId || ''}
              disabled={!draft.model}
              onChange={(event) => {
                updatePresets({ ...entry, selectedPresetId: event.target.value || null })
                setEditing(null)
              }}
            >
              <option value="">服务默认</option>
              {entry.presets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.name}
                </option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              className="text-button"
              disabled={!draft.model || entry.presets.length >= 16}
              onClick={() => editPreset()}
            >
              添加推理预设
            </button>
            <button
              className="text-button"
              disabled={!entry.selectedPresetId}
              onClick={() =>
                editPreset(entry.presets.find((item) => item.id === entry.selectedPresetId))
              }
            >
              编辑预设
            </button>
            <button
              className="text-button"
              disabled={!entry.selectedPresetId}
              onClick={() => {
                updatePresets({
                  ...entry,
                  selectedPresetId: null,
                  presets: entry.presets.filter((item) => item.id !== entry.selectedPresetId),
                })
                setEditing(null)
              }}
            >
              删除预设
            </button>
          </div>
          {editing && (
            <div className="preset-editor">
              <label>
                预设名称
                <input
                  value={presetName}
                  onChange={(event) => setPresetName(event.target.value)}
                  placeholder="例如：深入"
                />
              </label>
              <label>
                参数模式
                <select
                  value={presetMode}
                  onChange={(event) => {
                    setPresetMode(event.target.value as 'simple' | 'advanced')
                    setPresetValue('')
                  }}
                >
                  <option value="simple">强度字符串</option>
                  <option value="advanced">JSON 参数</option>
                </select>
              </label>
              <label>
                {presetMode === 'simple' ? '推理强度值' : '推理参数 JSON'}
                <textarea
                  value={presetValue}
                  onChange={(event) => setPresetValue(event.target.value)}
                  placeholder={
                    presetMode === 'simple' ? '例如：high' : '{"thinking":{"type":"enabled"}}'
                  }
                  rows={presetMode === 'simple' ? 2 : 5}
                />
              </label>
              <small>
                {presetMode === 'simple'
                  ? '作为 reasoning_effort 发送；可填写服务支持的值。'
                  : '填写服务文档中的推理参数；不能覆盖模型、会议文字或凭证。'}
              </small>
              <div className="button-row">
                <button className="secondary-button" onClick={applyPreset}>
                  应用预设
                </button>
                <button className="text-button" onClick={() => setEditing(null)}>
                  取消编辑
                </button>
              </div>
            </div>
          )}
          <label className="check-label">
            <input
              type="checkbox"
              checked={draft.stream}
              onChange={(event) => change({ stream: event.target.checked })}
            />
            使用流式接口
          </label>
          <small>按服务支持情况选择，部分模型需要开启。</small>
        </div>
        <div className="service-footer">
          <p className="recipient-note">
            生成纪要会将该会议的文字发送至 {recipient || '所填服务'}，可能产生 API 调用费用。
          </p>
          <div className="button-row">
            <button
              className="secondary-button"
              disabled={!!network || !!editing || !draft.model || knownNontext}
              onClick={() => void run('check')}
            >
              测试连接
            </button>
            <button
              className="primary-button"
              disabled={!!editing || knownNontext}
              onClick={() =>
                void (async () => {
                  if (await mutate(() => window.paa.saveModelService(draft), '服务已保存。')) {
                    setDraft({ ...draft, apiKey: '' })
                    setSavedDraft(JSON.stringify({ ...draft, apiKey: '' }))
                    setHasKey(true)
                  }
                })()
              }
            >
              {busy ? '正在保存…' : '保存服务'}
            </button>
            {saved && (
              <button
                className="secondary-button"
                disabled={list.activeProfileId === draft.id || hasUnsavedChanges || knownNontext}
                onClick={() =>
                  void mutate(() => window.paa.selectModelService(draft.id), '已切换纪要服务。')
                }
              >
                用于纪要
              </button>
            )}
            {saved && (
              <button className="text-button" disabled={!!network} onClick={() => void load(id)}>
                还原已保存
              </button>
            )}
            {saved && (
              <button
                className="text-button danger-text"
                onClick={() =>
                  void (async () => {
                    if (
                      await mutate(
                        () => window.paa.removeModelService(draft.id),
                        '服务已移除，已有纪要保留。',
                      )
                    ) {
                      onRemove()
                    }
                  })()
                }
              >
                移除服务
              </button>
            )}
          </div>
        </div>
      </fieldset>
      {network && <p role="status">{network}</p>}
      {check && (
        <p role="status" className="connection-success">
          {check}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert" className="audio-warning">
          {error}
        </p>
      )}
    </section>
  )
}
