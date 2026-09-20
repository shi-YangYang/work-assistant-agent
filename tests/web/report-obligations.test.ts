import type { ReportObligation } from '@paa/api-contracts'
import { describe, expect, it } from 'vitest'
import {
  obligationLabel,
  obligationTarget,
  reportDeadline,
} from '../../apps/web/src/features/reports/utils/obligations'

const obligation: ReportObligation = {
  id: 'obligation',
  ownerId: 'employee',
  name: null,
  kind: 'daily',
  period: '2027-01-04',
  periodEnd: '2027-01-04',
  timezone: 'Asia/Shanghai',
  deadlineAt: '2027-01-04T10:00:00Z',
  state: 'pending',
  submittedAt: null,
  reportId: null,
}
describe('report inbox navigation', () => {
  it('opens the period without creating a report or invoking a model', () => {
    expect(obligationTarget(obligation)).toBe('/reports?view=todo&kind=daily&period=2027-01-04')
    expect(obligationTarget({ ...obligation, reportId: 'saved' })).toBe('/reports/saved')
  })
  it('renders the deadline in company time and separates read status from submission', () => {
    expect(reportDeadline(obligation)).toContain('18:00')
    expect(obligationLabel('pending')).toBe('待提交')
    expect(obligationLabel('overdue')).toBe('已逾期')
    expect(obligationLabel('cancelled')).toBe('已撤销')
  })
})
