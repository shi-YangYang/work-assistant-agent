export function customRangeError(start: string, end: string) {
  if (!start || !end) return '请完整填写开始与结束日期'
  const valid = (value: string) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '0001-01-01') return false
    const date = new Date(`${value}T00:00:00Z`)
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
  }
  if (!valid(start) || !valid(end)) return '请输入有效的开始与结束日期'
  if (end > '9999-12-30') return '结束日期不能晚于 9999-12-30'
  if (start > end) return '结束日期不能早于开始日期'
  return ''
}
