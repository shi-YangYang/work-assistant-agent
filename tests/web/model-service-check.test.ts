import type { ModelCheck } from '@paa/api-contracts'
import { beforeEach, expect, it, vi } from 'vitest'
import { useServiceCheck } from '../../apps/web/src/features/model-services/hooks/useServiceCheck'
import { newModel } from '../../apps/web/src/features/model-services/utils/service-drafts'

const state = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0, request: vi.fn() }))
vi.mock('react', async (load) => ({
  ...(await load<typeof import('react')>()),
  useState: <T>(initial: T) => {
    const slot = state.cursor++
    if (!(slot in state.slots)) state.slots[slot] = initial
    return [
      state.slots[slot],
      (next: T) => {
        state.slots[slot] = next
      },
    ]
  },
}))
vi.mock('@web/features/model-services/api/requests', () => ({
  checkServiceConfiguration: state.request,
}))

function context() {
  const model = newModel('chat-model')
  const draft = {
    id: 'service',
    name: '公司模型',
    baseUrl: 'https://example.com/v1',
    revision: 2,
    hasKey: true,
    models: [model],
  }
  return {
    draft,
    model,
    testPurpose: 'assistant' as const,
    capture: vi.fn(() => ({
      name: draft.name,
      baseUrl: draft.baseUrl,
      models: draft.models,
      expectedRevision: 2,
      apiKey: '',
    })),
    generationRef: { current: 0 },
    alive: { current: true },
    setBusy: vi.fn(),
    setError: vi.fn(),
    setConflict: vi.fn(),
    handleError: vi.fn(),
  }
}
function render(input: ReturnType<typeof context>) {
  state.cursor = 0
  return useServiceCheck(input)
}
beforeEach(() => {
  state.slots = []
  state.cursor = 0
  state.request.mockReset()
})

it('publishes a catalog only for the current service draft and echoed request version', async () => {
  const input = context()
  let finish!: (value: unknown) => void
  state.request.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  const pending = render(input).request('models')
  const [, payload] = state.request.mock.calls[0]
  expect(input.capture).toHaveBeenCalledWith(false)
  expect(payload).toMatchObject({
    serviceId: 'service',
    modelId: input.model.id,
    expectedRevision: 2,
    purpose: 'assistant',
  })
  input.generationRef.current++
  finish({
    models: ['stale-model'],
    source: 'api',
    truncated: false,
    draftVersion: payload.draftVersion,
  })
  await pending
  expect(render(input).catalog).toBeNull()
  state.request.mockImplementation((_kind, body) =>
    Promise.resolve({
      models: ['fresh-model'],
      source: 'api',
      truncated: false,
      draftVersion: body.draftVersion,
    }),
  )
  await render(input).request('models')
  expect(render(input).catalog?.models).toEqual(['fresh-model'])
})

it('rejects mismatched versions and ignores completion after unmount', async () => {
  const input = context()
  state.request.mockResolvedValue({
    models: ['wrong'],
    source: 'api',
    truncated: false,
    draftVersion: 'other-request',
  })
  await render(input).request('models')
  expect(render(input).catalog).toBeNull()
  state.request.mockImplementation((_kind, body) => {
    input.alive.current = false
    return Promise.resolve({ checks: [], draftVersion: body.draftVersion } as unknown as ModelCheck)
  })
  await render(input).request('test')
  expect(input.capture).toHaveBeenLastCalledWith(true)
  expect(render(input).check).toBeNull()
  expect(render(input).checkOpen).toBe(false)
})

it('opens the test result only after its matching request completes', async () => {
  const input = context()
  state.request.mockImplementation((_kind, body) =>
    Promise.resolve({ checks: [], draftVersion: body.draftVersion }),
  )
  await render(input).request('test')
  expect(render(input).check).toMatchObject({ checks: [] })
  expect(render(input).checkOpen).toBe(true)
  expect(render(input).testOpen).toBe(false)
  expect(input.setBusy.mock.calls).toEqual([['test'], ['']])
})
