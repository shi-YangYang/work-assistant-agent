import type { ReportObligation } from '@paa/api-contracts'

export const obligationLabel = (state: ReportObligation['state']) =>
  ({ pending: '待提交', overdue: '已逾期', submitted: '已提交', cancelled: '已撤销' })[state]

export function reportDeadline(item: ReportObligation) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: item.timezone,
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(item.deadlineAt))
}

export function obligationTarget(item: ReportObligation) {
  return item.reportId
    ? `/reports/${item.reportId}`
    : `/reports?view=todo&kind=${item.kind}&period=${item.period}`
}
