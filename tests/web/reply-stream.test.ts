import { describe, expect, it } from 'vitest'
import { reduceReply } from '../../apps/web/src/api/reply-stream'
import type { JobFeedback, ReplyEvent } from '@paa/api-contracts'

const feedback = { jobId: 'j', attempt: 1, fence: 2, state: 'running' } as JobFeedback
const sync: ReplyEvent = {
  type: 'sync',
  jobId: 'j',
  attempt: 1,
  fence: 2,
  generation: 3,
  seq: 4,
  text: '中文😀',
}
describe('reply cursor handoff', () => {
  it('joins only contiguous deltas and recovers gaps by sync', () => {
    const first = reduceReply(null, sync, feedback)
    const delta = { ...sync, type: 'delta', seq: 5, delta: '下一段' } as ReplyEvent
    const next = reduceReply(first, delta, feedback)
    expect(next?.reply.text).toBe('中文😀下一段')
    expect(reduceReply(next, delta, feedback)).toBe(next)
    expect(reduceReply(next, { ...delta, seq: 7 }, feedback)).toBe(next)
    expect(reduceReply(next, { ...sync, seq: 9, text: '完整恢复' }, feedback)?.reply.text).toBe(
      '完整恢复',
    )
  })
  it('rejects foreign jobs, old attempts, generations and post-terminal data', () => {
    const first = reduceReply(null, sync, feedback)
    for (const changes of [{ jobId: 'other' }, { attempt: 0 }, { fence: 1 }, { generation: 2 }])
      expect(reduceReply(first, { ...sync, seq: 9, ...changes }, feedback)).toBe(first)
    expect(reduceReply(first, { ...sync, seq: 5 }, { ...feedback, state: 'cancelled' })).toBe(first)
    expect(reduceReply(first, { ...sync, type: 'withdrawn', seq: 5 }, feedback)?.reply.text).toBe(
      '',
    )
    expect(
      reduceReply(first, { ...sync, generation: 4, seq: 1, text: '新尝试' }, feedback)?.reply.text,
    ).toBe('新尝试')
  })
})
