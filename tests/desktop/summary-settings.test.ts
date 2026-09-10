import { afterEach, describe, expect, it, vi } from 'vitest'
import { mkdtemp, readFile, rm, mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { randomUUID } from 'node:crypto'
import { SummarySettings, validateDraft } from '../../src/desktop/summary-settings'
import { selectedParameters } from '../../src/shared/reasoning'
import type { RuntimeConfig, ServiceDraft } from '../../src/shared/summary-contracts'
const directories: string[] = []
afterEach(async () => {
  await Promise.all(directories.splice(0).map((path) => rm(path, { recursive: true, force: true })))
})
const secrets = {
  isAsyncEncryptionAvailable: async () => true,
  encryptStringAsync: async (value: string) => Buffer.from([...value].reverse().join('')),
  decryptStringAsync: async (value: Buffer) => ({
    result: [...value.toString()].reverse().join(''),
  }),
}
const draft = (changes: Partial<ServiceDraft> = {}): ServiceDraft => ({
  id: randomUUID(),
  name: '测试服务',
  baseUrl: 'https://example.com/v1',
  model: 'unknown-next',
  apiKey: 'fake-test-secret',
  stream: false,
  models: [],
  ...changes,
})
async function fixture(): Promise<{
  root: string
  store: SummarySettings
  apply: ReturnType<typeof vi.fn<() => Promise<void>>>
}> {
  const root = await mkdtemp(join(tmpdir(), 'paa-settings-'))
  directories.push(root)
  const apply = vi.fn(async () => undefined)
  const store = new SummarySettings(root, secrets, apply)
  await store.load()
  return { root, store, apply }
}
describe('encrypted multi-service settings', () => {
  it('isolates keys and selection, restores after restart, edits inactive service without touching runtime', async () => {
    const { root, store, apply } = await fixture()
    const a = draft(),
      b = draft({ name: '另一个服务', apiKey: 'another-fake-key' })
    await store.upsert(a)
    await store.upsert(b)
    expect(store.list().activeProfileId).toBeNull()
    await store.select(a.id)
    expect(apply).toHaveBeenLastCalledWith(
      expect.objectContaining({ apiKey: a.apiKey, profileId: a.id }),
      true,
    )
    apply.mockClear()
    await store.upsert({ ...b, name: '改名', apiKey: '' })
    expect(apply).not.toHaveBeenCalled()
    expect(await readFile(join(root, 'model-services.json'), 'utf8')).not.toContain(a.apiKey)
    expect(JSON.stringify(store.get(a.id))).not.toContain('apiKey')
    const restarted = new SummarySettings(root, secrets, apply)
    await restarted.load()
    await restarted.sync()
    expect(restarted.list().activeProfileId).toBe(a.id)
    expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({ apiKey: a.apiKey }), true)
    await restarted.remove(a.id)
    expect(apply).toHaveBeenLastCalledWith(null, true)
    expect(restarted.list().profiles).toHaveLength(1)
  })
  it('serializes reconnect decryption with selection so old configuration cannot win', async () => {
    const { root, store } = await fixture()
    const a = draft(),
      b = draft({ name: 'service B' })
    await store.upsert(a)
    await store.upsert(b)
    await store.select(a.id)
    let entered!: () => void
    const started = new Promise<void>((resolve) => {
      entered = resolve
    })
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    let first = true
    const apply = vi.fn(async () => undefined)
    const delayed = new SummarySettings(
      root,
      {
        ...secrets,
        decryptStringAsync: async (value) => {
          if (first) {
            first = false
            entered()
            await gate
          }
          return secrets.decryptStringAsync(value)
        },
      },
      apply,
    )
    await delayed.load()
    const syncing = delayed.sync()
    await started
    const selecting = delayed.select(b.id)
    release()
    await Promise.all([syncing, selecting])
    expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({ profileId: b.id }), true)
    expect(delayed.list().activeProfileId).toBe(b.id)
  })
  it('draft discovery needs no model or save, changed URL cannot reuse an old key', async () => {
    const { store } = await fixture()
    const a = draft()
    await store.upsert(a)
    expect(await store.draftRuntime({ ...a, model: '', apiKey: '' }, false)).toMatchObject({
      model: '',
      apiKey: a.apiKey,
    })
    await expect(store.draftRuntime({ ...a, model: '', apiKey: '' }, true)).rejects.toThrow(
      '模型 ID',
    )
    await expect(
      store.draftRuntime({ ...a, baseUrl: 'https://other.test/v1', apiKey: '' }, false),
    ).rejects.toThrow('密钥')
    expect(store.list().activeProfileId).toBeNull()
  })
  it('save/apply failure rolls back disk and active config, encryption failure never writes plaintext', async () => {
    const { root, store, apply } = await fixture()
    const a = draft()
    await store.upsert(a)
    await store.select(a.id)
    const before = await readFile(join(root, 'model-services.json'), 'utf8')
    apply.mockRejectedValueOnce(new Error('core disconnected'))
    await expect(store.upsert({ ...a, name: 'should not save' })).rejects.toThrow('保留原配置')
    expect(await readFile(join(root, 'model-services.json'), 'utf8')).toBe(before)
    expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({ name: a.name }), true)
    const locked = new SummarySettings(
      root,
      { ...secrets, isAsyncEncryptionAvailable: async () => false },
      apply,
    )
    await locked.load()
    await expect(locked.upsert(draft())).rejects.toThrow('系统密钥保护不可用')
    expect(await readFile(join(root, 'model-services.json'), 'utf8')).toBe(before)
    await mkdir(join(root, 'model-services.staging'))
    await expect(store.upsert({ ...a, name: 'disk failed' })).rejects.toThrow()
    expect(store.get(a.id).name).toBe(a.name)
  })
  it('preserves custom presets per model; default omits parameters; nested values shared with check', async () => {
    const { store } = await fixture()
    const id = randomUUID(),
      a = draft({
        models: [
          {
            model: 'unknown-next',
            selectedPresetId: id,
            presets: [
              {
                id,
                name: '深入',
                mode: 'advanced',
                parameters: {
                  thinking: { enabled: true, budget: 1234 },
                  reasoning_effort: 'new-strength',
                },
              },
            ],
          },
        ],
      })
    await store.upsert(a)
    expect((await store.draftRuntime({ ...a, apiKey: '' }, true)).parameters).toEqual({
      thinking: { enabled: true, budget: 1234 },
      reasoning_effort: 'new-strength',
    })
    expect(selectedParameters(a.models, 'different-model')).toEqual({})
    expect(selectedParameters([{ ...a.models[0], selectedPresetId: null }], a.model)).toEqual({})
    expect(
      selectedParameters(
        [
          {
            model: a.model,
            selectedPresetId: id,
            presets: [{ id, name: '快', mode: 'simple', value: 'future-fast' }],
          },
        ],
        a.model,
      ),
    ).toEqual({ reasoning_effort: 'future-fast' })
  })
  it('validates trusted model eligibility before save, selection and draft check without mutating settings', async () => {
    const { root, apply } = await fixture()
    let blocked = false
    const validate = vi.fn(async (config: RuntimeConfig) => {
      if (blocked && config.model === 'unknown-next') throw new Error('非文本模型')
    })
    const store = new SummarySettings(root, secrets, apply, false, validate)
    const a = draft()
    await store.upsert(a)
    blocked = true // A refreshed directory identified the formerly unknown model.
    const before = await readFile(join(root, 'model-services.json'), 'utf8')
    await expect(store.upsert({ ...a, apiKey: '' })).rejects.toThrow('非文本模型')
    await expect(store.select(a.id)).rejects.toThrow('非文本模型')
    await expect(store.draftRuntime({ ...a, apiKey: '' }, true)).rejects.toThrow('非文本模型')
    expect(await readFile(join(root, 'model-services.json'), 'utf8')).toBe(before)
    expect(store.list().activeProfileId).toBeNull()
    expect(apply).not.toHaveBeenCalled()
    validate.mockClear()
    await store.draftRuntime({ ...a, apiKey: '' }, false)
    expect(validate).not.toHaveBeenCalled() // Refresh must remain available.
    await store.upsert({ ...a, apiKey: '', model: 'genuinely-unknown' })
    await store.select(a.id)
    expect(store.list().activeProfileId).toBe(a.id)
  })
  it('rejects malformed identities, unsafe URL, protected nested fields and huge settings', () => {
    for (const changes of [
      { id: [randomUUID()] },
      { baseUrl: 'https://x.test/v1?secret=x' },
      { baseUrl: 'http://x.test' },
      { stream: 'yes' },
      { models: [null] },
    ])
      expect(() => validateDraft({ ...draft(), ...changes })).toThrow()
    for (const parameters of [
      { model: 'other' },
      { thinking: { tools: [] } },
      JSON.parse('{"__proto__":null}'),
      { thinking: { expression: '${key}' } },
    ]) {
      const id = randomUUID()
      expect(() =>
        validateDraft(
          draft({
            models: [
              {
                model: 'unknown-next',
                selectedPresetId: id,
                presets: [{ id, name: 'bad', mode: 'advanced', parameters }],
              },
            ],
          }),
        ),
      ).toThrow()
    }
    const id = randomUUID()
    expect(() =>
      validateDraft({
        ...draft(),
        models: [
          {
            model: 'm',
            selectedPresetId: id,
            presets: [{ id: [id], name: 'bad', mode: 'simple', value: 'hi' }],
          },
        ],
      }),
    ).toThrow()
  })
})
