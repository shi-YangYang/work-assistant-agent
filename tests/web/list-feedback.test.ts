import type { Job, JobFeedback } from '@paa/api-contracts'
import { describe, expect, it } from 'vitest'
import {
  acceptFeedback,
  reportNeedsPolling,
  visibleFeedback,
} from '../../apps/web/src/api/job-feedback'
import { filterParams, pageParams } from '../../apps/web/src/utils/list-state'
import { detailReturn, detailState } from '../../apps/web/src/utils/navigation'

const feedback: JobFeedback = {
  jobId: 'job',
  attempt: 1,
  fence: 2,
  seq: 3,
  state: 'running',
  stage: 'generating',
  text: '部分正文',
  error: '',
  updatedAt: '2026-09-15T10:00:00Z',
}
const job: Job = {
  id: 'job',
  kind: 'message',
  targetId: 'message',
  attempt: 1,
  fence: 2,
  state: 'running',
  phase: 'assistant',
  error: '',
  updatedAt: feedback.updatedAt,
}

it('polls only active report jobs, never history snapshots or terminal results', () => {
  for (const state of ['queued', 'running'] as const)
    expect(reportNeedsPolling({ job: { ...job, kind: 'report', state } })).toBe(true)
  for (const state of [
    'succeeded',
    'awaiting_input',
    'awaiting_retry',
    'failed',
    'cancelled',
  ] as const)
    expect(reportNeedsPolling({ job: { ...job, kind: 'report', state } })).toBe(false)
  expect(reportNeedsPolling({ job: null })).toBe(false)
  expect(reportNeedsPolling({ historical: true, job: { ...job, kind: 'report' } })).toBe(false)
})

describe('work pagination and return context', () => {
  it('retains filters and all previous cursors through detail return and resets on a new filter', () => {
    let params = new URLSearchParams('q=资料&status=blocked')
    params = pageParams(params, 'next', 'first-time-id')
    params = pageParams(params, 'next', 'second-time-id')
    const state = detailState({ pathname: '/work', search: '?' + params, state: null })
    const back = detailReturn('/work/id', state)
    const restored = new URL(back.path, 'http://test').searchParams
    expect(restored.getAll('after')).toEqual(['first-time-id', 'second-time-id'])
    expect(pageParams(restored, 'previous').getAll('after')).toEqual(['first-time-id'])
    const changed = filterParams(restored, { q: '旧记录' })
    expect(changed.getAll('after')).toEqual([])
    expect(changed.get('q')).toBe('旧记录')
    expect(changed.get('status')).toBe('blocked')
  })
})
describe('resumable chat presentation', () => {
  it('replaces snapshots without concatenation and ignores old attempts, fences and sequences', () => {
    expect(acceptFeedback(feedback, { ...feedback, text: '重复' }, 'job')).toBe(feedback)
    expect(acceptFeedback(feedback, { ...feedback, seq: 2, text: '旧片段' }, 'job')).toBe(feedback)
    expect(acceptFeedback(feedback, { ...feedback, attempt: 0, seq: 99 }, 'job')).toBe(feedback)
    expect(acceptFeedback(feedback, { ...feedback, fence: 1, seq: 99 }, 'job')).toBe(feedback)
    expect(acceptFeedback(feedback, { ...feedback, jobId: 'another' }, 'job')).toBe(feedback)
    expect(
      acceptFeedback(feedback, { ...feedback, seq: 4, text: '完整临时正文' }, 'job')?.text,
    ).toBe('完整临时正文')
  })
  it('lets the authoritative completed message win even if the terminal SSE packet never arrives', () => {
    expect(visibleFeedback({ ...job, state: 'awaiting_input' }, feedback)).toBeNull()
    expect(visibleFeedback({ ...job, state: 'succeeded' }, feedback)).toBeNull()
    expect(visibleFeedback({ ...job, state: 'cancelled' }, feedback)).toBeNull()
    expect(visibleFeedback({ ...job, attempt: 2, fence: 3 }, feedback)).toBeNull()
    expect(
      visibleFeedback({ ...job, state: 'awaiting_retry', error: '连接中断' }, feedback),
    ).toMatchObject({ text: '部分正文', state: 'awaiting_retry', error: '连接中断' })
  })
})
