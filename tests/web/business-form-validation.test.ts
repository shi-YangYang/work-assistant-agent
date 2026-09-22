import type { Draft, Progress, Report, Work, WorkMessage } from '@paa/api-contracts'
import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../apps/web/src/api/client'
import { BusyButton } from '../../apps/web/src/components/BusyButton'
import { ErrorNotice } from '../../apps/web/src/components/ErrorNotice'
import { Modal } from '../../apps/web/src/components/Modal'
import { correctTranscript } from '../../apps/web/src/features/assistant/api/requests'
import { TranscriptEditor } from '../../apps/web/src/features/assistant/components/TranscriptEditor'
import { submitReport } from '../../apps/web/src/features/reports/api/requests'
import { ReportDetail } from '../../apps/web/src/features/reports/components/ReportDetail'
import {
  createWork,
  updateProgressDraft,
  updateWorkProgress,
} from '../../apps/web/src/features/work/api/requests'
import { CreateWork } from '../../apps/web/src/features/work/components/CreateWork'
import { ProgressEditor } from '../../apps/web/src/features/work/components/ProgressEditor'
import { ProgressFields } from '../../apps/web/src/features/work/components/ProgressFields'
import { WorkEditor } from '../../apps/web/src/features/work/components/WorkEditor'

const state = vi.hoisted(() => ({
  slots: [] as unknown[],
  cursor: 0,
  drafts: {} as Record<string, unknown>,
  data: null as unknown,
  text: '',
}))
vi.mock('react', async (load) => ({
  ...(await load<typeof import('react')>()),
  useState: <T>(initial: T | (() => T)) => {
    const slot = state.cursor++
    if (!(slot in state.slots))
      state.slots[slot] = typeof initial === 'function' ? (initial as () => T)() : initial
    return [
      state.slots[slot],
      (next: T) => {
        state.slots[slot] = next
      },
    ]
  },
}))
vi.mock('../../apps/web/src/lib/workspace', () => ({
  useWorkspace: () => ({
    drafts: state.drafts,
    setDraft: vi.fn(),
    notify: vi.fn(),
    identity: { member: { id: 'owner', role: 'employee' } },
  }),
}))
vi.mock('../../apps/web/src/hooks/useResource', () => ({
  useResource: () => ({ data: state.data, error: '', refresh: vi.fn() }),
}))
vi.mock('react-router', async (load) => ({
  ...(await load<typeof import('react-router')>()),
  useNavigate: () => vi.fn(),
  useLocation: () => ({ pathname: '/reports/report', search: '' }),
}))
vi.mock('../../apps/web/src/features/work/api/requests', async (load) => ({
  ...(await load<typeof import('../../apps/web/src/features/work/api/requests')>()),
  createWork: vi.fn(),
  updateProgressDraft: vi.fn(),
  updateWorkProgress: vi.fn(),
}))
vi.mock('../../apps/web/src/features/assistant/api/requests', async (load) => ({
  ...(await load<typeof import('../../apps/web/src/features/assistant/api/requests')>()),
  correctTranscript: vi.fn(),
}))
vi.mock('../../apps/web/src/features/reports/api/requests', async (load) => ({
  ...(await load<typeof import('../../apps/web/src/features/reports/api/requests')>()),
  submitReport: vi.fn(),
}))

function nodes(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(nodes)
  if (!isValidElement<Record<string, unknown>>(node)) return []
  return [node, ...nodes(node.props.children as ReactNode)]
}
function render(component: () => ReactNode) {
  state.cursor = 0
  return component()
}
function submit(tree: ReactNode) {
  return (
    nodes(tree).find((node) => node.type === 'form')!.props.onSubmit as (
      event: unknown,
    ) => Promise<void>
  )({ preventDefault: vi.fn(), currentTarget: {} })
}
const progress: Progress = {
  title: '   ',
  summary: '',
  status: 'in_progress',
  blocker: '',
  nextStep: '',
  dueDate: null,
}
const report = (): Report => ({
  id: 'report',
  ownerId: 'owner',
  kind: 'daily',
  period: '2026-09-22',
  periodEnd: '2026-09-22',
  timezone: 'Asia/Shanghai',
  revision: 1,
  publishedRevision: 0,
  managementRevision: 1,
  content: { completed: '', ongoing: '  ', blockers: '', next: '' },
  candidate: null,
  job: null,
  revisions: [],
  updatedAt: '2026-09-22T00:00:00Z',
  sourceIds: [],
})

beforeEach(() => {
  state.slots = []
  state.drafts = {}
  state.data = null
  state.text = ''
  vi.clearAllMocks()
})

it.each(['create', 'work', 'draft'] as const)(
  'blocks whitespace titles before the %s request and shows the field error',
  async (kind) => {
    state.drafts['work:new'] = { content: progress, key: 'key' }
    const component = () =>
      kind === 'create'
        ? CreateWork({ onClose: vi.fn(), onSaved: vi.fn() })
        : kind === 'work'
          ? WorkEditor({
              work: { ...progress, id: 'work', revision: 1 } as Work,
              onClose: vi.fn(),
              onSaved: vi.fn(),
            })
          : ProgressEditor({
              draft: { id: 'draft', content: progress, revision: 1, workId: null } as Draft,
              onClose: vi.fn(),
              onSaved: vi.fn(),
            })
    await submit(render(component))
    expect(createWork).not.toHaveBeenCalled()
    expect(updateWorkProgress).not.toHaveBeenCalled()
    expect(updateProgressDraft).not.toHaveBeenCalled()
    expect(
      nodes(render(component)).find((node) => node.type === ProgressFields)!.props.errors,
    ).toMatchObject({ title: '请填写工作标题' })
  },
)

it('keeps rejected work fields beside the fields in the open dialog', async () => {
  state.drafts['work:new'] = { content: { ...progress, title: '项目' }, key: 'key' }
  const error = new ApiError(422, 'validation_error', '请检查输入项')
  error.fieldErrors = { dueDate: '请输入有效日期' }
  vi.mocked(createWork).mockRejectedValueOnce(error)
  const component = () => CreateWork({ onClose: vi.fn(), onSaved: vi.fn() })
  await submit(render(component))
  expect(
    nodes(render(component)).find((node) => node.type === ProgressFields)!.props.errors,
  ).toEqual(error.fieldErrors)
})

it('allows clearing a transcript and leaves failed saves visible inside its modal', async () => {
  vi.stubGlobal(
    'FormData',
    class {
      get() {
        return state.text
      }
    },
  )
  const close = vi.fn(),
    changed = vi.fn()
  const component = () =>
    TranscriptEditor({
      transcript: true,
      setTranscript: close,
      setBusy: vi.fn(),
      message: { id: 'message', transcript: '误识别', transcriptRevision: 2 } as WorkMessage,
      onChange: changed,
      busy: false,
    })
  try {
    await submit(render(component))
    expect(correctTranscript).toHaveBeenCalledWith(expect.anything(), {
      text: '',
      expectedRevision: 2,
    })
    expect(close).toHaveBeenCalledWith(false)
    const conflict = new ApiError(409, 'revision_conflict', '转写已被更新，请读取最新内容')
    vi.mocked(correctTranscript).mockRejectedValueOnce(conflict)
    await submit(render(component))
    const modal = nodes(render(component)).find((node) => node.type === Modal)!
    expect(nodes(modal).find((node) => node.type === ErrorNotice)!.props.children).toBe(conflict)
  } finally {
    vi.unstubAllGlobals()
  }
})

it('opens the report editor for empty content instead of issuing a submission', () => {
  state.data = report()
  const component = () => ReportDetail({ recordId: 'report' })
  const button = nodes(render(component)).find(
    (node) => node.type === 'button' && node.props.children === '提交报告',
  )!
  ;(button.props.onClick as () => void)()
  const updated = nodes(render(component))
  expect(updated.some((node) => node.type === 'form')).toBe(true)
  expect(updated.find((node) => node.type === ErrorNotice)!.props.children).toBe('请先填写报告内容')
  expect(submitReport).not.toHaveBeenCalled()
})

it('shows rejected report submission inside the confirmation modal', async () => {
  state.data = { ...report(), content: { ...report().content, completed: '已完成' } }
  const component = () => ReportDetail({ recordId: 'report' })
  const button = nodes(render(component)).find(
    (node) => node.type === 'button' && node.props.children === '提交报告',
  )!
  ;(button.props.onClick as () => void)()
  const conflict = new ApiError(409, 'revision_conflict', '报告已更新')
  vi.mocked(submitReport).mockRejectedValueOnce(conflict)
  const confirmation = nodes(render(component)).find(
    (node) => node.type === BusyButton && node.props.children === '确认提交',
  )!
  await (confirmation.props.onClick as () => Promise<void>)()
  const modal = nodes(render(component)).find((node) => node.type === Modal)!
  expect(nodes(modal).find((node) => node.type === ErrorNotice)!.props.children).toBe(conflict)
})
