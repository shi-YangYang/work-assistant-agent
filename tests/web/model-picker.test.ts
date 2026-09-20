import {
  Children,
  isValidElement,
  type ComponentProps,
  type ReactElement,
  type ReactNode,
} from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { Modal } from '../../apps/web/src/components/Modal'
import { ModelPicker } from '../../apps/web/src/features/model-services/components/ModelPicker'
import { ModelServices } from '../../apps/web/src/features/model-services/components/ModelServices'
import { ServiceModelLibrary } from '../../apps/web/src/features/model-services/components/ServiceModelLibrary'
import { newModel } from '../../apps/web/src/features/model-services/utils/service-drafts'

const state = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  session: vi.fn(),
  check: vi.fn(),
}))
vi.mock('react', async (load) => ({
  ...(await load<typeof import('react')>()),
  useState: <T>(initial: T | (() => T)) => {
    const slots = state.slots
    const slot = state.cursor++
    if (!(slot in slots))
      slots[slot] = typeof initial === 'function' ? (initial as () => T)() : initial
    return [
      slots[slot],
      (next: T | ((previous: T) => T)) => {
        slots[slot] =
          typeof next === 'function' ? (next as (previous: T) => T)(slots[slot] as T) : next
      },
    ]
  },
}))
vi.mock('@web/lib/workspace', () => ({
  useWorkspace: () => ({ setDraft: vi.fn(), notify: vi.fn() }),
}))
vi.mock('@web/features/model-services/hooks/useServiceDraftSession', () => ({
  useServiceDraftSession: state.session,
}))
vi.mock('@web/features/model-services/hooks/useServiceCheck', () => ({
  useServiceCheck: state.check,
}))

type Props = { children?: ReactNode; [key: string]: unknown }
function nodes(tree: ReactNode): ReactElement<Props>[] {
  const result: ReactElement<Props>[] = []
  Children.forEach(tree, (child) => {
    if (isValidElement<Props>(child)) result.push(child, ...nodes(child.props.children))
  })
  return result
}
function find(tree: ReactNode, predicate: (node: ReactElement<Props>) => boolean) {
  const node = nodes(tree).find(predicate)
  if (!node) throw new Error('Missing picker control')
  return node
}
function input(tree: ReactNode) {
  return find(tree, (node) => node.type === 'input' && node.props.type !== 'checkbox')
    .props as Props & { value: string; onChange: (event: { target: { value: string } }) => void }
}
function click(tree: ReactNode, label: string) {
  const control = find(tree, (node) => node.type === 'button' && node.props.children === label)
  ;(control.props.onClick as () => void)()
}

// Like the existing Hook tests, run real component callbacks with persistent
// state slots. The parent emits the picker identity: a changed key or removal
// discards its slots, matching the mount boundary this regression depends on.
function editor() {
  const parentSlots: unknown[] = []
  let pickerSlots: unknown[] = []
  let previous: ReactElement<ComponentProps<typeof ModelPicker>> | undefined
  let parent: ReactNode
  const render = () => {
    state.slots = parentSlots
    state.cursor = 0
    parent = ModelServices()
    const picker = nodes(parent).find((node) => node.type === ModelPicker) as
      ReactElement<ComponentProps<typeof ModelPicker>> | undefined
    if (!picker || !previous || picker.key !== previous.key) pickerSlots = []
    previous = picker
    if (!picker) return null
    state.slots = pickerSlots
    state.cursor = 0
    return ModelPicker(picker.props)
  }
  render()
  return {
    render,
    open: (mode: 'catalog' | 'manual') => {
      const library = find(parent, (node) => node.type === ServiceModelLibrary)
      ;(library.props.onAdd as (mode: 'catalog' | 'manual') => void)(mode)
      return render()
    },
  }
}

beforeEach(() => {
  const draft = {
    id: 'service',
    name: '公司模型',
    baseUrl: 'https://example.com/v1',
    revision: 1,
    hasKey: true,
    models: [newModel('existing-model')],
  }
  state.session.mockReturnValue({
    resource: { data: { services: [draft] }, refresh: vi.fn(), error: '' },
    services: [draft],
    drafts: {},
    draft,
    allServices: [draft],
    dirty: false,
    connectionReady: true,
    update: vi.fn(),
    changeAddress: vi.fn(),
    capture: vi.fn(),
    selection: { selected: draft.id, setSelected: vi.fn(), select: vi.fn() },
    credentials: { keys: {}, setKeys: vi.fn(), blocker: { state: 'unblocked' } },
    lifecycle: { generationRef: { current: 0 }, alive: { current: true } },
  })
  state.check.mockReturnValue({
    catalog: { models: ['available-model'], source: 'api', truncated: false },
    setCatalog: vi.fn(),
    check: null,
    setCheck: vi.fn(),
    checkOpen: false,
    setCheckOpen: vi.fn(),
    testOpen: false,
    setTestOpen: vi.fn(),
    request: vi.fn(),
  })
})

it('carries the catalog search into manual input through the parent mode change', () => {
  const page = editor()
  input(page.open('catalog')).onChange({ target: { value: 'custom-chat-model' } })
  click(page.render(), '手动输入')
  const manual = page.render()
  expect(input(manual).value).toBe('custom-chat-model')
  const submit = find(
    manual,
    (node) => node.type === 'button' && node.props.children === '添加模型',
  )
  expect(submit.props.disabled).toBe(false)
})

it.each(['catalog', 'manual'] as const)(
  'resets %s input after closing and reopening the picker',
  (mode) => {
    const page = editor()
    input(page.open(mode)).onChange({ target: { value: 'discard-this-input' } })
    const edited = page.render()
    expect(input(edited).value).toBe('discard-this-input')
    const modal = find(edited, (node) => node.type === Modal)
    ;(modal.props.onClose as () => void)()
    expect(page.render()).toBeNull()
    expect(input(page.open(mode)).value).toBe('')
  },
)
