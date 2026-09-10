import { randomUUID } from 'node:crypto'
import { readFile, writeFile, rename, mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { ID_PATTERN } from '../shared/contracts'
import { selectedParameters, validateParameters } from '../shared/reasoning'
import type {
  RuntimeConfig,
  ServiceDraft,
  ServiceList,
  ServiceProfile,
} from '../shared/summary-contracts'

type StoredProfile = Omit<ServiceProfile, 'hasKey'> & { encryptedKey: string }
type State = {
  version: 1
  activeProfileId: string | null
  autoGenerate: boolean
  profiles: StoredProfile[]
}
export interface SecretStorage {
  isAsyncEncryptionAvailable(): Promise<boolean>
  encryptStringAsync(value: string): Promise<Buffer>
  decryptStringAsync(value: Buffer): Promise<{ result: string }>
}
export function boundedText(value: unknown, max: number, label: string, empty = false): string {
  if (
    typeof value !== 'string' ||
    value.length > max ||
    (!empty && !value.trim()) ||
    [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
  )
    throw new Error(`${label}无效，请检查长度和特殊字符。`)
  return value.trim()
}
export function validateDraft(input: unknown, allowLoopback = false): ServiceDraft {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('服务配置无效。')
  const draft = structuredClone(input) as ServiceDraft
  if (
    Object.keys(draft).sort().join() !==
      ['id', 'name', 'baseUrl', 'model', 'stream', 'models', 'apiKey'].sort().join() ||
    typeof draft.id !== 'string' ||
    !ID_PATTERN.test(draft.id)
  )
    throw new Error('服务配置字段无效。')
  draft.name = boundedText(draft.name, 80, '服务名称')
  draft.baseUrl = boundedText(draft.baseUrl, 2048, 'API 地址').replace(/\/+$/, '')
  let url: URL
  try {
    url = new URL(draft.baseUrl)
  } catch {
    throw new Error('API 地址无效。')
  }
  if (
    !url.hostname ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.protocol !== 'https:' &&
      !(
        allowLoopback &&
        url.protocol === 'http:' &&
        ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
      ))
  )
    throw new Error('API 地址须为不含用户名、查询参数或片段的 HTTPS Base URL。')
  draft.model = boundedText(draft.model, 256, '模型 ID', true)
  draft.apiKey = boundedText(draft.apiKey, 4096, '密钥', true)
  if (typeof draft.stream !== 'boolean' || !Array.isArray(draft.models) || draft.models.length > 32)
    throw new Error('模型配置无效或超过 32 个。')
  const names = new Set<string>()
  for (const model of draft.models) {
    if (
      !model ||
      typeof model !== 'object' ||
      Array.isArray(model) ||
      Object.keys(model).sort().join() !== ['model', 'selectedPresetId', 'presets'].sort().join()
    )
      throw new Error('推理预设字段无效。')
    model.model = boundedText(model.model, 256, '模型 ID')
    if (names.has(model.model) || !Array.isArray(model.presets) || model.presets.length > 16)
      throw new Error('模型重复或推理预设超过 16 个。')
    names.add(model.model)
    const ids = new Set<string>()
    for (const preset of model.presets) {
      if (
        !preset ||
        typeof preset.id !== 'string' ||
        !ID_PATTERN.test(preset.id) ||
        ids.has(preset.id)
      )
        throw new Error('推理预设标识无效。')
      ids.add(preset.id)
      preset.name = boundedText(preset.name, 80, '预设名称')
      if (preset.mode === 'simple') {
        if (Object.keys(preset).sort().join() !== ['id', 'name', 'mode', 'value'].sort().join())
          throw new Error('推理预设字段无效。')
        preset.value = boundedText(preset.value, 128, '推理强度')
        validateParameters({ reasoning_effort: preset.value })
      } else if (preset.mode === 'advanced') {
        if (
          Object.keys(preset).sort().join() !== ['id', 'name', 'mode', 'parameters'].sort().join()
        )
          throw new Error('推理预设字段无效。')
        validateParameters(preset.parameters)
      } else throw new Error('推理预设模式无效。')
    }
    if (model.selectedPresetId !== null && !ids.has(model.selectedPresetId))
      throw new Error('所选推理预设不存在。')
  }
  if (Buffer.byteLength(JSON.stringify(draft)) > 48 * 1024)
    throw new Error('服务配置超过 48 KiB，请减少保存的模型预设。')
  return draft
}

export class SummarySettings {
  private state: State = { version: 1, activeProfileId: null, autoGenerate: true, profiles: [] }
  private serial: Promise<unknown> = Promise.resolve()
  private loadError = false
  constructor(
    private readonly root: string,
    private readonly secrets: SecretStorage,
    private readonly apply: (config: RuntimeConfig | null, automatic: boolean) => Promise<void>,
    private readonly allowLoopback = false,
    private readonly validateModel: (config: RuntimeConfig) => Promise<void> = async () =>
      undefined,
  ) {}
  async load(): Promise<void> {
    try {
      const text = await readFile(join(this.root, 'model-services.json'), 'utf8')
      if (Buffer.byteLength(text) > 1024 * 1024) throw new Error('Too large')
      const state = JSON.parse(text) as State
      if (
        state.version !== 1 ||
        !Array.isArray(state.profiles) ||
        state.profiles.length > 16 ||
        typeof state.autoGenerate !== 'boolean' ||
        (state.activeProfileId !== null &&
          (typeof state.activeProfileId !== 'string' || !ID_PATTERN.test(state.activeProfileId)))
      )
        throw new Error('Invalid settings')
      const ids = new Set<string>()
      for (const profile of state.profiles) {
        const { encryptedKey, revision, ...draft } = profile
        if (
          typeof revision !== 'string' ||
          !ID_PATTERN.test(revision) ||
          typeof encryptedKey !== 'string' ||
          encryptedKey.length > 16000 ||
          ids.has(profile.id)
        )
          throw new Error('Invalid key')
        validateDraft({ ...draft, apiKey: '' }, this.allowLoopback)
        ids.add(profile.id)
      }
      if (state.activeProfileId && !ids.has(state.activeProfileId))
        throw new Error('Missing profile')
      this.state = state
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') this.loadError = true
    }
  }
  private ensure(): void {
    if (this.loadError) throw new Error('模型设置无法读取，请保留设置文件并检查权限或内容。')
  }
  list(): ServiceList {
    this.ensure()
    return {
      activeProfileId: this.state.activeProfileId,
      autoGenerate: this.state.autoGenerate,
      profiles: this.state.profiles.map(({ id, name, baseUrl, model, encryptedKey }) => ({
        id,
        name,
        baseUrl,
        model,
        hasKey: !!encryptedKey,
      })),
    }
  }
  get(id: string): ServiceProfile {
    this.ensure()
    const profile = this.state.profiles.find((item) => item.id === id)
    if (!profile) throw new Error('服务配置不存在。')
    const { encryptedKey, ...publicProfile } = structuredClone(profile)
    return { ...publicProfile, hasKey: !!encryptedKey }
  }
  private async decrypt(profile: StoredProfile): Promise<string> {
    try {
      if (!(await this.secrets.isAsyncEncryptionAvailable())) throw new Error('Unavailable')
      return (await this.secrets.decryptStringAsync(Buffer.from(profile.encryptedKey, 'base64')))
        .result
    } catch {
      throw new Error('无法解锁已保存密钥，请重新输入并保存；录音和转写仍可使用。')
    }
  }
  private runtime(profile: StoredProfile, apiKey: string): RuntimeConfig {
    return {
      profileId: profile.id,
      revision: profile.revision,
      name: profile.name,
      baseUrl: profile.baseUrl,
      model: profile.model,
      stream: profile.stream,
      apiKey,
      parameters: selectedParameters(profile.models, profile.model),
    }
  }
  private async active(state: State): Promise<RuntimeConfig | null> {
    const profile = state.profiles.find((item) => item.id === state.activeProfileId)
    return profile ? this.runtime(profile, await this.decrypt(profile)) : null
  }
  sync(): Promise<void> {
    const operation = this.serial.then(async () => {
      this.ensure()
      await this.apply(await this.active(this.state), this.state.autoGenerate)
    })
    this.serial = operation.catch(() => undefined)
    return operation
  }
  async draftRuntime(input: unknown, requireModel: boolean): Promise<RuntimeConfig> {
    this.ensure()
    const draft = validateDraft(input, this.allowLoopback)
    if (requireModel && !draft.model) throw new Error('请选择或填写模型 ID。')
    const old = this.state.profiles.find((item) => item.id === draft.id)
    const key =
      draft.apiKey || (old && old.baseUrl === draft.baseUrl ? await this.decrypt(old) : '')
    if (!key) throw new Error('请输入此 API 地址对应的密钥。')
    const config = this.runtime({ ...draft, encryptedKey: '', revision: randomUUID() }, key)
    if (requireModel) await this.validateModel(config)
    return config
  }
  private async write(state: State): Promise<void> {
    await mkdir(this.root, { recursive: true })
    const temporary = join(this.root, 'model-services.staging')
    await writeFile(temporary, JSON.stringify(state), { mode: 0o600 })
    await rename(temporary, join(this.root, 'model-services.json'))
  }
  private mutate(action: (state: State) => Promise<void> | void): Promise<ServiceList> {
    const operation = this.serial.then(async () => {
      this.ensure()
      const before = this.state,
        next = structuredClone(before)
      await action(next)
      const activeChanged =
        next.activeProfileId !== before.activeProfileId ||
        next.autoGenerate !== before.autoGenerate ||
        next.profiles.find((item) => item.id === next.activeProfileId)?.revision !==
          before.profiles.find((item) => item.id === before.activeProfileId)?.revision
      const config = activeChanged ? await this.active(next) : null
      await this.write(next)
      try {
        if (activeChanged) await this.apply(config, next.autoGenerate)
      } catch {
        await this.write(before)
        try {
          await this.apply(await this.active(before), before.autoGenerate)
        } catch {
          /* Reconnect restores the preserved settings. */
        }
        throw new Error('设置未应用，已保留原配置；请重新连接后重试。')
      }
      this.state = next
      return this.list()
    })
    this.serial = operation.catch(() => undefined)
    return operation
  }
  upsert(input: unknown): Promise<ServiceList> {
    return this.mutate(async (state) => {
      const draft = validateDraft(input, this.allowLoopback)
      if (!draft.model) throw new Error('请选择或填写模型 ID。')
      const old = state.profiles.find((item) => item.id === draft.id)
      if (!old && state.profiles.length >= 16) throw new Error('最多保存 16 家服务。')
      if (!draft.apiKey && (!old || old.baseUrl !== draft.baseUrl))
        throw new Error('请输入此 API 地址对应的密钥。')
      let encryptedKey = old?.encryptedKey || ''
      if (draft.apiKey) {
        try {
          if (!(await this.secrets.isAsyncEncryptionAvailable())) throw new Error('Unavailable')
          encryptedKey = (await this.secrets.encryptStringAsync(draft.apiKey)).toString('base64')
        } catch {
          throw new Error('系统密钥保护不可用，密钥未保存；请检查系统权限后重试。')
        }
      }
      const profile: StoredProfile = {
        id: draft.id,
        name: draft.name,
        baseUrl: draft.baseUrl,
        model: draft.model,
        stream: draft.stream,
        models: draft.models,
        revision: randomUUID(),
        encryptedKey,
      }
      await this.validateModel(this.runtime(profile, draft.apiKey || (await this.decrypt(profile))))
      state.profiles = [...state.profiles.filter((item) => item.id !== profile.id), profile]
    })
  }
  remove(id: string): Promise<ServiceList> {
    return this.mutate((state) => {
      state.profiles = state.profiles.filter((item) => item.id !== id)
      if (state.activeProfileId === id) state.activeProfileId = null
    })
  }
  select(id: string | null): Promise<ServiceList> {
    return this.mutate(async (state) => {
      if (id !== null && !state.profiles.some((item) => item.id === id))
        throw new Error('服务配置不存在。')
      const profile = state.profiles.find((item) => item.id === id)
      if (profile) await this.validateModel(this.runtime(profile, await this.decrypt(profile)))
      state.activeProfileId = id
    })
  }
  automatic(value: boolean): Promise<ServiceList> {
    return this.mutate((state) => {
      state.autoGenerate = value
    })
  }
}
