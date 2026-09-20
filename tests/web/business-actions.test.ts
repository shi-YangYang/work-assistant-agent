import type { BusinessAction } from '@paa/api-contracts'
import { expect, it } from 'vitest'
import { actionStateLabel } from '../../apps/web/src/features/assistant/components/BusinessActionCard'

const base: BusinessAction = {
  id: 'action',
  messageId: 'message',
  action: 'generate_report',
  label: '生成报告',
  state: 'running',
  revision: 1,
  createdAt: '',
}
it('distinguishes queued report generation, failed generation and committed results', () => {
  expect(actionStateLabel(base)).toBe('正在生成')
  expect(
    actionStateLabel({
      ...base,
      job: {
        id: 'job',
        targetId: 'report',
        kind: 'report',
        state: 'awaiting_retry',
        phase: '',
        error: '',
        updatedAt: '',
      },
    }),
  ).toBe('尚未生成')
  expect(actionStateLabel({ ...base, state: 'pending' })).toBe('等待确认')
  expect(actionStateLabel({ ...base, state: 'succeeded' })).toBe('已完成')
  expect(actionStateLabel({ ...base, state: 'conflict' })).toBe('内容已变化')
})
