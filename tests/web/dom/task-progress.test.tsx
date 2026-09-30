// @vitest-environment jsdom
import type { Job, TaskNode } from '@paa/api-contracts'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { JobNotice } from '../../../apps/web/src/features/jobs/components/JobNotice'

const node: TaskNode = {
  id: 'read',
  parentId: null,
  kind: 'tool',
  label: '读取工作',
  state: 'running',
  attempts: 1,
  maxAttempts: 4,
  retries: 0,
  totalRetries: 0,
  round: 0,
  nextRetryAt: null,
  error: '',
  errorCode: '',
  canRetry: false,
  presentation: { type: 'operation' },
}
const job: Job = {
  id: 'job',
  targetId: 'message',
  kind: 'message',
  state: 'running',
  phase: 'assistant',
  error: '',
  updatedAt: '2026-01-01',
  attempt: 0,
  fence: 1,
  nodes: [node],
}
afterEach(cleanup)

it('keeps the same expanded operation row when the subject resolves and processing advances', () => {
  const view = (value: Job) => <JobNotice job={value} refresh={vi.fn()} showNodes />
  const mounted = render(view(job))
  const details = mounted.container.querySelector('details')!
  fireEvent.click(details.querySelector('summary')!)
  const row = mounted.container.querySelector('[data-node-id="read"]')
  mounted.rerender(
    view({
      ...job,
      updatedAt: '2026-01-02',
      nodes: [
        { ...node, state: 'succeeded', presentation: { type: 'operation', subject: '登录页优化' } },
        {
          ...node,
          id: 'model',
          kind: 'model',
          label: '整理工具结果',
          presentation: { type: 'activity' },
        },
      ],
    }),
  )
  expect(mounted.container.querySelector('details')).toBe(details)
  expect(details.open).toBe(true)
  expect(mounted.container.querySelector('[data-node-id="read"]')).toBe(row)
  expect(row?.textContent).toContain('读取工作：登录页优化')
  expect(details.querySelectorAll('li')).toHaveLength(1)
  expect(details.querySelector('summary')?.textContent).toContain('整理工具结果')
  mounted.rerender(view({ ...job, state: 'succeeded', nodes: [{ ...node, state: 'succeeded' }] }))
  expect(details.open).toBe(true)
  expect(mounted.container.querySelector('summary')?.textContent).toContain('已完成 · 1 项操作')
  expect(mounted.container.querySelector('[data-node-id="read"]')).toBe(row)
  expect(mounted.container.querySelector('details')?.open).toBe(true)
})
