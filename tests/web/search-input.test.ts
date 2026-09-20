import type { InputHTMLAttributes, ReactElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SearchInput } from '../../apps/web/src/components/SearchInput'

// Exercise the component's real event handlers/effects with deterministic clocks.
// Like use-resource.test.ts, this needs no browser or extra DOM dependency.
const hooks = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  changed: false,
  effects: new Map<number, { deps: unknown[]; cleanup?: () => void }>(),
  pending: [] as (() => void)[],
}))
vi.mock('react', () => ({
  useState: <T>(initial: T) => {
    const slot = hooks.cursor++
    if (!(slot in hooks.slots)) hooks.slots[slot] = initial
    return [
      hooks.slots[slot],
      (next: T) => {
        hooks.slots[slot] = next
        hooks.changed = true
      },
    ]
  },
  useRef: <T>(initial: T) => {
    const slot = hooks.cursor++
    if (!(slot in hooks.slots)) hooks.slots[slot] = { current: initial }
    return hooks.slots[slot]
  },
  useEffect: (setup: () => void | (() => void), deps: unknown[]) => {
    const slot = hooks.cursor++
    const previous = hooks.effects.get(slot)
    if (previous && deps.every((value, index) => Object.is(value, previous.deps[index]))) return
    hooks.pending.push(() => {
      previous?.cleanup?.()
      hooks.effects.set(slot, { deps, cleanup: setup() || undefined })
    })
  },
}))
const render = (value: string, onSearch: (q: string) => void, resetKey = 0) => {
  let element: ReactElement<InputHTMLAttributes<HTMLInputElement>>
  do {
    hooks.cursor = 0
    hooks.changed = false
    hooks.pending = []
    element = SearchInput({ value, onSearch, resetKey })
  } while (hooks.changed)
  hooks.pending.forEach((effect) => effect())
  return element.props
}
const change = (props: InputHTMLAttributes<HTMLInputElement>, value: string) =>
  props.onChange!({ target: { value } } as Parameters<NonNullable<typeof props.onChange>>[0])
const key = (
  props: InputHTMLAttributes<HTMLInputElement>,
  value: string,
  name: string,
  composing = false,
) =>
  props.onKeyDown!({
    key: name,
    currentTarget: { value },
    nativeEvent: { isComposing: composing },
    preventDefault: vi.fn(),
  } as unknown as Parameters<NonNullable<typeof props.onKeyDown>>[0])
const unmount = () => hooks.effects.forEach((effect) => effect.cleanup?.())
beforeEach(() => {
  vi.useFakeTimers()
  hooks.slots = []
  hooks.effects.clear()
})
afterEach(() => {
  unmount()
  vi.useRealTimers()
})

it('combines rapid typing into one search and keeps current input visible', async () => {
  const search = vi.fn()
  let props = render('', search)
  for (const value of ['p', 'pl', 'pla', 'plan']) {
    change(props, value)
    props = render('', search)
    expect(props.value).toBe(value)
    await vi.advanceTimersByTimeAsync(50)
  }
  expect(search).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(250)
  expect(search.mock.calls).toEqual([['plan']])
})

it('waits for Chinese composition to finish; Enter submits and clearing is immediate', async () => {
  const search = vi.fn()
  let props = render('', search)
  props.onCompositionStart!({} as never)
  change(props, 'fangan')
  key(props, 'fangan', 'Enter', true)
  await vi.advanceTimersByTimeAsync(1000)
  expect(search).not.toHaveBeenCalled()
  props.onCompositionEnd!({ currentTarget: { value: '方案' } } as never)
  props = render('', search)
  key(props, '方案', 'Enter')
  expect(search.mock.calls).toEqual([['方案']])
  props = render('方案', search)
  change(props, '')
  expect(search.mock.calls).toEqual([['方案'], ['']])
  await vi.advanceTimersByTimeAsync(1000)
  expect(search).toHaveBeenCalledTimes(2)
})

it('uses the latest filters callback and cancels pending input on navigation/reset/unmount', async () => {
  const oldFilters = vi.fn(),
    currentFilters = vi.fn()
  change(render('', oldFilters), '报价')
  render('', currentFilters)
  await vi.advanceTimersByTimeAsync(300)
  expect(oldFilters).not.toHaveBeenCalled()
  expect(currentFilters.mock.calls).toEqual([['报价']])
  change(render('报价', currentFilters), '待取消')
  expect(render('', currentFilters).value).toBe('')
  await vi.advanceTimersByTimeAsync(300)
  expect(currentFilters).toHaveBeenCalledTimes(1)
  change(render('', currentFilters), '草稿')
  expect(render('', currentFilters, 1).value).toBe('')
  await vi.advanceTimersByTimeAsync(300)
  expect(currentFilters).toHaveBeenCalledTimes(1)
  change(render('', currentFilters, 1), '离开页面')
  unmount()
  await vi.advanceTimersByTimeAsync(300)
  expect(currentFilters).toHaveBeenCalledTimes(1)
})
