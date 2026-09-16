import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setCsrf, useResource } from '../../apps/web/src/api'

// Keep hook state across explicit refresh/path renders while exercising the
// real effect, fetch boundary, AbortController and browser events without a DOM.
const hooks = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  setup: undefined as (() => void | (() => void)) | undefined,
  cleanup: undefined as (() => void) | undefined,
}))
vi.mock('react', () => ({
  useState: <T>(initial: T) => {
    const slot = hooks.cursor++
    if (!(slot in hooks.slots)) hooks.slots[slot] = initial
    return [
      hooks.slots[slot],
      (next: T | ((previous: T) => T)) => {
        hooks.slots[slot] =
          typeof next === 'function' ? (next as (previous: T) => T)(hooks.slots[slot] as T) : next
      },
    ]
  },
  useRef: <T>(initial: T) => {
    const slot = hooks.cursor++
    if (!(slot in hooks.slots)) hooks.slots[slot] = { current: initial }
    return hooks.slots[slot]
  },
  useCallback: <T>(callback: T) => callback,
  useEffect: (setup: () => void | (() => void)) => {
    hooks.setup = setup
  },
}))

const render = (path: string | null, interval = 1000) => {
  hooks.cleanup?.()
  hooks.cursor = 0
  const resource = useResource<{ value: string }>(path, interval)
  hooks.cleanup = hooks.setup?.() || undefined
  return resource
}
const limited = () => new Response('{}', { status: 429, headers: { 'Retry-After': '60' } })
const success = () => Promise.resolve(new Response(JSON.stringify({ value: 'fresh' })))
let surface: EventTarget, document: EventTarget & { hidden: boolean }
beforeEach(() => {
  vi.useFakeTimers()
  hooks.slots = []
  hooks.cursor = 0
  hooks.setup = hooks.cleanup = undefined
  surface = Object.assign(new EventTarget(), {
    location: { pathname: '/work' },
    innerWidth: 390,
    innerHeight: 844,
  })
  document = Object.assign(new EventTarget(), { hidden: false })
  vi.stubGlobal('window', surface)
  vi.stubGlobal('document', document)
  setCsrf('test')
})
afterEach(() => {
  hooks.cleanup?.()
  setCsrf('')
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('keeps timer, browser recovery and manual refresh behind one persistent retry deadline', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(limited()).mockImplementation(success)
  vi.stubGlobal('fetch', fetch)
  let resource = render('/work-items')
  await vi.advanceTimersByTimeAsync(0)
  expect(fetch).toHaveBeenCalledTimes(1)
  surface.dispatchEvent(new Event('online'))
  document.dispatchEvent(new Event('visibilitychange'))
  resource.refresh()
  resource = render('/work-items')
  await vi.advanceTimersByTimeAsync(30000)
  resource.refresh()
  render('/work-items')
  surface.dispatchEvent(new Event('online'))
  document.dispatchEvent(new Event('visibilitychange'))
  await vi.advanceTimersByTimeAsync(29999)
  expect(fetch).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(1)
  expect(fetch).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(1000)
  expect(fetch).toHaveBeenCalledTimes(3)
})

it('defers a manual non-polling read once, without creating a polling loop', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(limited()).mockImplementation(success)
  vi.stubGlobal('fetch', fetch)
  const resource = render('/members', 0)
  await vi.advanceTimersByTimeAsync(0)
  resource.refresh()
  render('/members', 0)
  await vi.advanceTimersByTimeAsync(59999)
  expect(fetch).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(1)
  expect(fetch).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(120000)
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('resets the retry deadline when the resource path or verified identity changes', async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(limited()))
  vi.stubGlobal('fetch', fetch)
  render('/work-items/one')
  await vi.advanceTimersByTimeAsync(0)
  render('/work-items/two')
  await vi.advanceTimersByTimeAsync(0)
  expect(fetch).toHaveBeenCalledTimes(2)
  setCsrf('another-identity')
  surface.dispatchEvent(new Event('online'))
  await vi.advanceTimersByTimeAsync(0)
  expect(fetch).toHaveBeenCalledTimes(3)
  render(null)
  render('/work-items/two')
  await vi.advanceTimersByTimeAsync(0)
  expect(fetch).toHaveBeenCalledTimes(4)
  hooks.cleanup?.()
  hooks.cleanup = undefined
  await vi.advanceTimersByTimeAsync(120000)
  expect(fetch).toHaveBeenCalledTimes(4)
})
