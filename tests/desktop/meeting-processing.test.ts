import { EventEmitter } from 'node:events'
import { PassThrough, Writable } from 'node:stream'
import type { ChildProcessWithoutNullStreams } from 'node:child_process'
import { afterEach, expect, it, vi } from 'vitest'
import { JsonLineClient } from '../../src/desktop/json-line-client'
import { MeetingProcessingQueue } from '../../src/renderer/meeting-processing-queue'
import type { Result, TranscriptionStatus } from '../../src/shared/contracts'
import type { SummaryView } from '../../src/shared/summary-contracts'

afterEach(() => vi.useRealTimers())

it('keeps 100 visible row consumers bounded across cancellation, re-entry and processing handoff', async () => {
  vi.useFakeTimers()
  type Request = { id: string; method: string; params: { meetingId: string } }
  const pending: Request[] = []
  const sent: Request[] = []
  let maximumPending = 0
  const child = Object.assign(new EventEmitter(), {
    stdout: new PassThrough(),
    stderr: new PassThrough(),
    stdin: new Writable({
      write(chunk, _encoding, done) {
        const request = JSON.parse(chunk.toString()) as Request
        pending.push(request)
        sent.push(request)
        maximumPending = Math.max(maximumPending, client.pendingCount)
        done()
      },
    }),
  })
  const client = new JsonLineClient(
    child as unknown as ChildProcessWithoutNullStreams,
    vi.fn(),
    1_000_000,
  )
  const queue = new MeetingProcessingQueue({
    getTranscriptionStatus: (meetingId) =>
      client.request('transcript', undefined, { meetingId }) as Promise<
        Result<TranscriptionStatus>
      >,
    getSummary: (meetingId) =>
      client.request('summary', undefined, { meetingId }) as Promise<Result<SummaryView>>,
  })
  let transcriptState: TranscriptionStatus['state'] = 'completed'
  let summaryState: NonNullable<SummaryView['task']>['state'] | null = null
  const respond = async (request: Request): Promise<void> => {
    const value =
      request.method === 'transcript'
        ? { state: transcriptState }
        : { task: summaryState ? { state: summaryState } : null, result: null }
    child.stdout.write(JSON.stringify({ id: request.id, result: { ok: true, value } }) + '\n')
    await vi.advanceTimersByTimeAsync(0)
  }
  const settle = async (): Promise<void> => {
    while (pending.length) await respond(pending.shift()!)
  }
  const discarded = vi.fn()
  const listen = (listener: (label: string) => void): (() => void)[] =>
    Array.from({ length: 100 }, (_, index) => queue.subscribe(`meeting-${index}`, listener))
  let leave = listen(discarded)
  expect(client.pendingCount).toBe(4)
  // Changing pages cannot release the four real IPCs before their replies arrive.
  for (let visit = 0; visit < 20; visit++) {
    leave.forEach((unsubscribe) => unsubscribe())
    leave = listen(discarded)
  }
  expect(sent).toHaveLength(4)
  leave.forEach((unsubscribe) => unsubscribe())
  const current = vi.fn()
  leave = listen(current)
  await settle()
  expect(discarded).not.toHaveBeenCalled()
  expect(current).toHaveBeenCalledTimes(100)
  expect(current).toHaveBeenCalledWith('文字已完成')
  expect(sent.filter((request) => request.method === 'summary')).toHaveLength(100)
  expect(maximumPending).toBe(4)
  expect(client.pendingCount).toBe(0)
  const settledCount = sent.length
  await vi.advanceTimersByTimeAsync(5000)
  expect(sent).toHaveLength(settledCount)
  leave.forEach((unsubscribe) => unsubscribe())
  await vi.advanceTimersByTimeAsync(120_000)
  expect(sent).toHaveLength(settledCount)

  // Returning/manual refresh gets fresh state immediately; ASR completion is not final.
  const handoff = vi.fn()
  let stop = queue.subscribe('meeting-0', handoff)
  expect(pending).toHaveLength(1)
  await settle()
  summaryState = 'queued'
  await vi.advanceTimersByTimeAsync(30_000)
  await settle()
  expect(handoff).toHaveBeenLastCalledWith('纪要排队中')
  summaryState = 'running'
  await vi.advanceTimersByTimeAsync(5000)
  await settle()
  expect(handoff).toHaveBeenLastCalledWith('正在生成纪要')
  summaryState = 'interrupted'
  await vi.advanceTimersByTimeAsync(5000)
  await settle()
  expect(handoff).toHaveBeenLastCalledWith('纪要待重试')
  stop()

  for (const [state, label] of [
    ['queued', '转写排队中'],
    ['running', '正在转写'],
    ['draining', '转写收尾中'],
    ['failed', '转写待继续'],
  ] as const) {
    transcriptState = state
    summaryState = null
    stop = queue.subscribe('meeting-0', handoff)
    await settle()
    expect(handoff).toHaveBeenLastCalledWith(label)
    stop()
  }

  // Leaving during the summary read must not update the old row or start queued work.
  const late = vi.fn()
  stop = queue.subscribe('meeting-old', late)
  await respond(pending.shift()!)
  expect(pending[0].method).toBe('summary')
  stop()
  await settle()
  await vi.advanceTimersByTimeAsync(120_000)
  expect(late).not.toHaveBeenCalled()
  expect(client.pendingCount).toBe(0)
  expect(vi.getTimerCount()).toBe(0)
})
