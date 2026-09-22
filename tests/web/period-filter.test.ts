import type { DateRange } from '@paa/api-contracts'
import { isValidElement, type InputHTMLAttributes, type ReactElement, type ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { PeriodFilter } from '../../apps/web/src/components/PeriodFilter'
import { customRangeError } from '../../apps/web/src/utils/date-range'

const hooks = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0, changed: false }))
vi.mock('react', async (load) => ({
  ...(await load<typeof import('react')>()),
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
  useId: () => 'range-error',
}))
function nodes(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(nodes)
  if (!isValidElement<Record<string, unknown>>(node)) return []
  return [node, ...nodes(node.props.children as ReactNode)]
}
const range: DateRange = {
  period: 'this_week',
  start: '2026-09-21',
  end: '2026-09-27',
  timezone: 'Asia/Shanghai',
}
function render(
  params: URLSearchParams,
  change: (values: Record<string, string>) => void,
  currentRange: DateRange | undefined = range,
) {
  let tree: ReactNode
  do {
    hooks.cursor = 0
    hooks.changed = false
    tree = PeriodFilter({ params, range: currentRange, change })
  } while (hooks.changed)
  const elements = nodes(tree)
  return {
    fields: elements
      .filter((node) => node.type === 'input')
      .map((node) => node.props as InputHTMLAttributes<HTMLInputElement>),
    error: elements.find((node) => node.props.role === 'alert')?.props.children,
    select: elements.find((node) => node.type === 'select')!.props.onChange as (event: {
      target: { value: string }
    }) => void,
  }
}
const edit = (field: InputHTMLAttributes<HTMLInputElement>, value: string) =>
  field.onChange!({ target: { value } } as never)
beforeEach(() => {
  hooks.slots = []
})

it('retains incomplete or reversed drafts and only publishes a complete valid range', () => {
  const params = new URLSearchParams({ period: 'custom', start: range.start, end: range.end })
  const change = vi.fn()
  edit(render(params, change).fields[1], '')
  expect(change).not.toHaveBeenCalled()
  expect(render(params, change).fields[1].value).toBe('')
  expect(render(params, change).error).toContain('请完整填写开始与结束日期')
  edit(render(params, change).fields[1], '2026-09-20')
  expect(change).not.toHaveBeenCalled()
  expect(render(params, change).fields[1]['aria-invalid']).toBe(true)
  edit(render(params, change).fields[0], '2026-09-19')
  expect(change).toHaveBeenCalledExactlyOnceWith({ start: '2026-09-19', end: '2026-09-20' })
  expect(render(params, change).error).toBeUndefined()
})

it('replaces abandoned drafts after navigation and starts custom filtering with complete dates', () => {
  const params = new URLSearchParams({ period: 'custom', start: range.start, end: range.end })
  const change = vi.fn()
  edit(render(params, change).fields[1], '')
  params.set('end', '2026-09-25')
  expect(render(params, change).fields[1].value).toBe('2026-09-25')
  render(new URLSearchParams(), change).select({ target: { value: 'custom' } })
  expect(change).toHaveBeenLastCalledWith({ period: 'custom', start: range.start, end: range.end })
  render(new URLSearchParams(), change, undefined).select({ target: { value: 'this_month' } })
  expect(change).toHaveBeenLastCalledWith({ period: 'this_month', start: '', end: '' })
})

it('rejects invalid calendar dates and the unsupported next-day boundary', () => {
  expect(customRangeError('2026-02-29', '2026-03-01')).toContain('有效')
  expect(customRangeError('2024-02-29', '2024-03-01')).toBe('')
  expect(customRangeError('0000-01-01', '0001-01-01')).toContain('有效')
  expect(customRangeError('9999-12-30', '9999-12-31')).toContain('9999-12-30')
  expect(customRangeError('9999-12-30', '9999-12-30')).toBe('')
})
