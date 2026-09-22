import type { Rules } from '@paa/api-contracts'

export function revealRuleErrors(form: HTMLFormElement) {
  const fields = form.querySelectorAll<HTMLInputElement>('[aria-invalid="true"]')
  for (const field of fields) {
    let section = field.closest('details')
    while (section) {
      section.open = true
      section = section.parentElement?.closest('details') ?? null
    }
  }
  const first = fields[0]
  if (!first) return
  first.scrollIntoView({ block: 'center' })
  first.focus({ preventScroll: true })
}

export function reportRuleErrors(value: Pick<Rules, 'daily' | 'weekly'>): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const kind of ['daily', 'weekly'] as const) {
    const schedule = value[kind]
    if (schedule.enabled && !schedule.days.length) errors[`${kind}.days`] = '请至少选择一个汇报日。'
    if (kind === 'weekly' && schedule.enabled && schedule.days.length !== 1)
      errors[`${kind}.days`] = '周报请选择一个汇报日。'
    if (schedule.enabled || schedule.generateTime || schedule.deadline) {
      for (const field of ['generateTime', 'deadline'] as const) {
        if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(schedule[field]))
          errors[`${kind}.${field}`] = '请完整填写时间，格式为 时:分，例如 09:00。'
      }
      if (
        !errors[`${kind}.generateTime`] &&
        !errors[`${kind}.deadline`] &&
        schedule.deadline < schedule.generateTime
      )
        errors[`${kind}.deadline`] = '提交截止时间不得早于草稿生成时间。'
    }
    if (
      !Number.isInteger(schedule.beforeMinutes ?? 30) ||
      (schedule.beforeMinutes ?? 30) < 0 ||
      (schedule.beforeMinutes ?? 30) > 1440
    )
      errors[`${kind}.beforeMinutes`] = '提醒时间需为 0–1440 之间的整数分钟。'
  }
  return errors
}
