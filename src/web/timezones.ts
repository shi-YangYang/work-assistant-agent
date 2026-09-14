export const companyTimezones = [
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Europe/London',
  'Europe/Paris',
  'America/New_York',
  'America/Los_Angeles',
  'UTC',
]
const labels: Record<string, string> = {
  'Asia/Shanghai': '北京时间（UTC+08:00）',
  'Asia/Hong_Kong': '香港时间（UTC+08:00）',
  'Asia/Tokyo': '东京时间（UTC+09:00）',
  'Asia/Singapore': '新加坡时间（UTC+08:00）',
  'Europe/London': '伦敦时间（自动夏令时）',
  'Europe/Paris': '巴黎时间（自动夏令时）',
  'America/New_York': '纽约时间（自动夏令时）',
  'America/Los_Angeles': '洛杉矶时间（自动夏令时）',
  UTC: '协调世界时（UTC）',
}
export function timezoneLabel(value: string) {
  if (labels[value]) return labels[value]
  try {
    const name = new Intl.DateTimeFormat('zh-CN', { timeZone: value, timeZoneName: 'longGeneric' })
      .formatToParts(new Date())
      .find((part) => part.type === 'timeZoneName')?.value
    return name ? `${name}（${value}）` : value
  } catch {
    return value
  }
}
