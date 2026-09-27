import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import type {
  ModelEntry,
  ModelPresets,
  ReasoningPreset,
  ServiceDraft,
  ServiceList,
} from '../shared/summary-contracts'
import { validateParameters } from '@paa/model-config'
import type { Result } from '../shared/contracts'
const blank = (): ServiceDraft => ({
  id: crypto.randomUUID(),
  name: '新服务',
  baseUrl: '',
  apiKey: '',
  model: '',
  stream: true,
  models: [],
})
const initial: ServiceList = { profiles: [], activeProfileId: null, autoGenerate: true }
export function useModelSettings(visible: boolean) {
  const [list, setList] = useState(initial)
  const [selected, setSelected] = useState('')
  const [opened, setOpened] = useState<string[]>([])
  const [error, setError] = useState('')
  const [automaticBusy, setAutomaticBusy] = useState(false)
  useEffect(() => {
    if (!visible) return
    let alive = true
    void window.paa
      .listModelServices()
      .then((result) => {
        if (!alive) return
        if (!result.ok) {
          setError(result.message)
          return
        }
        setList(result.value)
        setError('')
        if (!selected) {
          const id =
            result.value.activeProfileId || result.value.profiles[0]?.id || crypto.randomUUID()
          setSelected(id)
          setOpened([id])
        }
      })
      .catch(() => {
        if (alive) setError('无法读取服务设置，请重新连接后重试。')
      })
    return () => {
      alive = false
    }
    // Refresh the saved list on entry; existing in-memory editors own their drafts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible])
  function select(id: string): void {
    setSelected(id)
    setOpened((previous) => (previous.includes(id) ? previous : [...previous, id]))
  }
  const active = list.profiles.find((profile) => profile.id === list.activeProfileId)
  const profiles = [
    ...list.profiles,
    ...opened
      .filter((id) => !list.profiles.some((profile) => profile.id === id))
      .map((id) => ({ id, name: '未保存服务', model: '' })),
  ]
  async function setAutomatic(checked: boolean): Promise<void> {
    setAutomaticBusy(true)
    setError('')
    try {
      const result = await window.paa.setAutomaticSummary(checked)
      if (result.ok) setList(result.value)
      else setError(result.message)
    } catch {
      setError('自动生成设置未保存，请重试。')
    } finally {
      setAutomaticBusy(false)
    }
  }
  return {
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
  }
}

export function useModelServiceEditor(
  id: string,
  list: ServiceList,
  setList: Dispatch<SetStateAction<ServiceList>>,
) {
  const [draft, setDraft] = useState<ServiceDraft>(() => ({ ...blank(), id }))
  const [tab, setTab] = useState<'connection' | 'model'>('connection')
  const [hasKey, setHasKey] = useState(false)
  const [savedDraft, setSavedDraft] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(() => list.profiles.some((profile) => profile.id === id))
  const [network, setNetwork] = useState('')
  const [directory, setDirectory] = useState<ModelEntry[] | null>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [check, setCheck] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [presetName, setPresetName] = useState('')
  const [presetMode, setPresetMode] = useState<'simple' | 'advanced'>('simple')
  const [presetValue, setPresetValue] = useState('')
  const epoch = useRef(0)
  useEffect(() => {
    if (list.profiles.some((profile) => profile.id === id)) void load(id)
    const lifetime = epoch
    return () => {
      lifetime.current++
    }
    // Each mounted service owns its draft and outstanding operations until removal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])
  function invalidate(clearDirectory = false): void {
    epoch.current++
    setCheck('')
    setNetwork('')
    setNotice('')
    setError('')
    if (clearDirectory) {
      setDirectory(null)
      setUpdatedAt(null)
    }
  }
  function change(fields: Partial<ServiceDraft>, clearDirectory = false): void {
    invalidate(clearDirectory)
    setDraft((previous) => ({ ...previous, ...fields }))
    if ('model' in fields) setEditing(null)
  }
  async function load(id: string): Promise<void> {
    invalidate(true)
    setLoading(true)
    const current = epoch.current
    let result
    try {
      result = await window.paa.getModelService(id)
    } catch {
      if (epoch.current === current) setError('无法读取服务，请重新连接后重试。')
      setLoading(false)
      return
    }
    if (epoch.current !== current) return
    setLoading(false)
    if (!result.ok) {
      setError(result.message)
      return
    }
    const configured = result.value.hasKey
    const { id: profileId, name, baseUrl, model, stream, models } = result.value
    const profile = { id: profileId, name, baseUrl, model, stream, models }
    setDraft({ ...profile, apiKey: '' })
    setSavedDraft(JSON.stringify({ ...profile, apiKey: '' }))
    setHasKey(configured)
    setEditing(null)
  }
  async function mutate(
    action: () => Promise<Result<ServiceList>>,
    message: string,
  ): Promise<boolean> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await action()
      if (!result.ok) {
        setError(result.message)
        return false
      }
      setList(result.value)
      setNotice(message)
      return true
    } catch {
      setError('操作未确认，请重新读取设置后检查。')
      return false
    } finally {
      setBusy(false)
    }
  }
  async function run(kind: 'models' | 'check'): Promise<void> {
    const current = ++epoch.current
    setError('')
    setCheck('')
    setNetwork(kind === 'models' ? '正在获取模型…' : '正在测试连接…')
    try {
      const start = await (kind === 'models'
        ? window.paa.requestModels(draft)
        : window.paa.checkModel(draft))
      if (!start.ok) throw new Error(start.message)
      while (epoch.current === current) {
        const response = await window.paa.getModelOperation(start.value.id)
        if (epoch.current !== current) return
        if (!response.ok) throw new Error(response.message)
        if (response.value.state === 'failed')
          throw new Error(response.value.error?.message || '请求失败，请检查设置。')
        if (response.value.state === 'completed' && response.value.result) {
          if (kind === 'check')
            setCheck(
              `连接成功 · ${response.value.result.elapsedMs} 毫秒。${response.value.result.message}`,
            )
          else {
            let models = response.value.result.models || []
            let more = response.value.result.hasMore
            while (more && epoch.current === current) {
              const next = await window.paa.getModelOperation(start.value.id, models.length)
              if (!next.ok) throw new Error(next.message)
              models = [...models, ...(next.value.result?.models || [])]
              more = next.value.result?.hasMore
            }
            if (epoch.current !== current) return
            setDirectory(models)
            setUpdatedAt(response.value.result.updatedAt || null)
          }
          break
        }
        setNetwork(
          response.value.state === 'queued'
            ? '请求排队中…'
            : kind === 'models'
              ? '正在获取模型…'
              : '正在测试连接…',
        )
        await new Promise((resolve) => setTimeout(resolve, 500))
      }
    } catch (failure) {
      if (epoch.current === current)
        setError(failure instanceof Error ? failure.message : '请求失败，请检查设置。')
    } finally {
      if (epoch.current === current) setNetwork('')
    }
  }
  const entry: ModelPresets = draft.models.find((item) => item.model === draft.model) || {
    model: draft.model,
    selectedPresetId: null,
    presets: [],
  }
  function updatePresets(value: ModelPresets): void {
    change({ models: [...draft.models.filter((item) => item.model !== draft.model), value] })
  }
  function editPreset(preset?: ReasoningPreset): void {
    setEditing(preset?.id || crypto.randomUUID())
    setPresetName(preset?.name || '')
    setPresetMode(preset?.mode || 'simple')
    setPresetValue(
      preset?.mode === 'advanced'
        ? JSON.stringify(preset.parameters, null, 2)
        : preset?.value || '',
    )
  }
  function applyPreset(): void {
    try {
      if (!editing || !presetName.trim() || presetName.length > 80)
        throw new Error('请填写不超过 80 字的预设名称。')
      let preset: ReasoningPreset
      if (presetMode === 'simple') {
        if (!presetValue.trim() || presetValue.length > 128)
          throw new Error('请填写不超过 128 字的推理强度值。')
        validateParameters({ reasoning_effort: presetValue.trim() })
        preset = { id: editing, name: presetName.trim(), mode: 'simple', value: presetValue.trim() }
      } else {
        const parameters: unknown = JSON.parse(presetValue)
        validateParameters(parameters)
        preset = { id: editing, name: presetName.trim(), mode: 'advanced', parameters }
      }
      updatePresets({
        ...entry,
        selectedPresetId: editing,
        presets: [...entry.presets.filter((item) => item.id !== editing), preset],
      })
      setEditing(null)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '推理参数无效。')
    }
  }
  const knownNontext =
    directory?.some((item) => item.id === draft.model.trim() && !item.selectable) === true
  const saved = list.profiles.some((item) => item.id === draft.id)
  const hasUnsavedChanges = JSON.stringify(draft) !== savedDraft
  let recipient = draft.baseUrl
  try {
    recipient = new URL(draft.baseUrl).host
  } catch {
    /* Incomplete form. */
  }
  return {
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
  }
}
