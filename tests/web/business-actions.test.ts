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

it('renders changed empty fields and actual blocker/next step from saved receipts', async () => {
  const { createElement } = await import('react')
  const { renderToStaticMarkup } = await import('react-dom/server')
  const { WorkActionDetails } =
    await import('../../apps/web/src/features/assistant/components/BusinessActionCard')
  const html = renderToStaticMarkup(
    createElement(WorkActionDetails, {
      action: {
        ...base,
        action: 'update_work',
        state: 'succeeded',
        details: { summary: '更新后的摘要', blocker: '', nextStep: '执行测试', dueDate: null },
        changedFields: ['summary', 'blocker', 'nextStep', 'dueDate'],
      },
    }),
  )
  expect(html).toContain('阻碍')
  expect(html).toContain('下一步')
  expect(html).toContain('执行测试')
  expect(html).toContain('截止日期')
  expect(html.match(/已清空/g)).toHaveLength(2)
})
