import type { Member } from '@paa/api-contracts'
import type { ComponentProps, ReactElement, ReactNode } from 'react'
import { createElement, isValidElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../apps/web/src/api/client'
import { ErrorNotice } from '../../apps/web/src/components/ErrorNotice'
import { FormField } from '../../apps/web/src/components/FormField'
import { createMember, resetMemberPassword } from '../../apps/web/src/features/members/api/requests'
import { MemberForm } from '../../apps/web/src/features/members/components/MemberForm'

// Run the component's actual event handlers without adding a DOM dependency.
const hooks = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  cleanups: [] as (() => void)[],
}))
vi.mock('react', async (load) => ({
  ...(await load<typeof import('react')>()),
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
  useEffect: (setup: () => (() => void) | void) => {
    const slot = hooks.cursor++
    if (slot in hooks.slots) return
    hooks.slots[slot] = true
    const cleanup = setup()
    if (cleanup) hooks.cleanups.push(cleanup)
  },
  useId: () => 'field-id',
}))
vi.mock('../../apps/web/src/features/members/api/requests', () => ({
  createMember: vi.fn(),
  resetMemberPassword: vi.fn(),
}))

const saved = vi.fn()
const closed = vi.fn()
const focus = vi.fn()
const member = { id: 'member', name: '员工' } as Member

function descendants(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(descendants)
  if (!isValidElement<Record<string, unknown>>(node)) return []
  return [node, ...descendants(node.props.children as ReactNode)]
}

function render(reset: Member | null = null) {
  hooks.cursor = 0
  const dialog = MemberForm({ member: reset, onClose: closed, onSaved: saved })
  const elements = descendants(dialog)
  const form = elements.find((element) => element.type === 'form')!.props as ComponentProps<'form'>
  ;(form.ref as { current: unknown }).current = {
    elements: { namedItem: (name: string) => ({ focus: () => focus(name) }) },
  }
  const field = (name: string) =>
    elements.find((element) => element.type === FormField && element.props.name === name)!
      .props as unknown as ComponentProps<typeof FormField>
  return {
    form,
    field,
    close: dialog.props.onClose,
    failure: elements.find((element) => element.type === ErrorNotice)!.props.children,
    submit: () => form.onSubmit!({ preventDefault: vi.fn() } as never) as unknown as Promise<void>,
  }
}

function change(name: string, value: string, reset: Member | null = null) {
  render(reset).field(name).onChange!({ currentTarget: { value } } as never)
}

function fill() {
  change('name', '1')
  change('username', '111')
  change('password', '1111')
}

beforeEach(() => {
  hooks.cleanups.forEach((cleanup) => cleanup())
  hooks.cleanups = []
  hooks.slots = []
  vi.clearAllMocks()
  vi.mocked(createMember).mockReset().mockResolvedValue({})
  vi.mocked(resetMemberPassword).mockReset().mockResolvedValue({})
})

it('validates on submit and blur, focuses the first error and clears corrected errors while typing', async () => {
  expect(render().form.noValidate).toBe(true)
  expect(render().field('name').error).toBeUndefined()
  await render().submit()
  expect(focus).toHaveBeenLastCalledWith('name')
  expect(render().field('name').error).toBe('请输入姓名')
  expect(createMember).not.toHaveBeenCalled()
  change('name', '1')
  expect(render().field('name').error).toBe('')
  change('username', '12')
  expect(render().field('username').error).toContain('3–80')
  change('username', 'a.b_c@d-e')
  expect(render().field('username').error).toBe('')
  change('username', '中文123')
  render().field('username').onBlur!({} as never)
  expect(render().field('username').error).toContain('字母、数字')
  fill()
  await render().submit()
  expect(createMember).toHaveBeenCalledExactlyOnceWith({
    name: '1',
    username: '111',
    password: '1111',
    role: 'employee',
  })
  expect(saved).toHaveBeenCalledOnce()
})

it('checks untouched fields on blur and uses the same password range for reset', async () => {
  change('username', 'x')
  expect(render().field('username').error).toBeUndefined()
  render().field('username').onBlur!({} as never)
  expect(render().field('username').error).toContain('3–80')
  change('password', '111', member)
  await render(member).submit()
  expect(render(member).field('password').error).toContain('4–128')
  expect(resetMemberPassword).not.toHaveBeenCalled()
  change('password', '1111', member)
  await render(member).submit()
  expect(resetMemberPassword).toHaveBeenCalledWith(member, { password: '1111' })
})

it('rejects whitespace-only names and normalizes surrounding name whitespace', async () => {
  fill()
  change('name', '   ')
  await render().submit()
  expect(render().field('name').error).toBe('请输入姓名')
  expect(createMember).not.toHaveBeenCalled()
  change('name', '  员工  ')
  await render().submit()
  expect(createMember).toHaveBeenCalledWith({
    name: '员工',
    username: '111',
    password: '1111',
    role: 'employee',
  })
})

it.each([null, member])(
  'accepts 128 Unicode characters and rejects 129 for member %s',
  async (reset) => {
    if (!reset) fill()
    change('password', '🔑'.repeat(129), reset)
    await render(reset).submit()
    expect(render(reset).field('password').error).toContain('4–128')
    expect(createMember).not.toHaveBeenCalled()
    expect(resetMemberPassword).not.toHaveBeenCalled()
    change('password', '🔑'.repeat(128), reset)
    await render(reset).submit()
    expect(saved).toHaveBeenCalledOnce()
  },
)

it('keeps API field errors in the dialog until edited and falls back for legacy validation paths', async () => {
  fill()
  const duplicate = new ApiError(409, 'username_taken', '账号已存在', 'conflict')
  duplicate.fieldErrors = { username: '该账号已存在，请更换账号' }
  vi.mocked(createMember).mockRejectedValueOnce(duplicate)
  await render().submit()
  expect(focus).toHaveBeenLastCalledWith('username')
  expect(render().field('username').error).toBe('该账号已存在，请更换账号')
  expect(render().failure).toBe('')
  render().field('username').onBlur!({} as never)
  expect(render().field('username').error).toBe('该账号已存在，请更换账号')
  change('username', '222')
  expect(render().field('username').error).toBe('')
  const legacy = new ApiError(422, 'validation_error', '请求不合法', 'validation')
  legacy.fields = ['body.password']
  vi.mocked(createMember).mockRejectedValueOnce(legacy)
  await render().submit()
  expect(render().field('password').error).toContain('4–128')
  expect(focus).toHaveBeenLastCalledWith('password')
})

it('prevents duplicate requests and closing while saving, and leaves network errors in the form', async () => {
  fill()
  let reject!: (error: Error) => void
  vi.mocked(createMember).mockImplementationOnce(
    () => new Promise((_, rejectRequest) => (reject = rejectRequest)),
  )
  const pending = render().submit()
  expect(render().form['aria-busy']).toBe(true)
  expect(render().field('username').readOnly).toBe(true)
  await render().submit()
  render().close()
  expect(createMember).toHaveBeenCalledOnce()
  expect(closed).not.toHaveBeenCalled()
  const error = new ApiError(0, 'network', '无法连接服务', 'network')
  reject(error)
  await pending
  expect(render().failure).toBe(error)
  expect(render().form['aria-busy']).toBe(false)
  render().close()
  expect(closed).toHaveBeenCalledOnce()
  hooks.cleanups.forEach((cleanup) => cleanup())
  hooks.slots = []
  expect(render().failure).toBe('')
  expect(render().field('username').error).toBeUndefined()
})

it('connects labels, hints and inline error messages to the invalid input', () => {
  const html = renderToStaticMarkup(
    createElement(FormField, {
      label: '账号',
      name: 'username',
      hint: '账号规则',
      error: '账号已存在',
      required: true,
    }),
  )
  expect(html).toContain('for="field-id"')
  expect(html).toContain('aria-invalid="true"')
  expect(html).toContain('aria-describedby="field-id-error"')
  expect(html).toContain('id="field-id-error" role="alert"')
  expect(html).not.toContain('账号规则')
  expect(html).not.toContain('pattern=')
})
