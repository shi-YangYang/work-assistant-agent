import type { SupportDiagnostics } from '@paa/api-contracts'

export function diagnosticPage(pathname: string) {
  const known = new Set([
    '/assistant',
    '/work',
    '/reports',
    '/team',
    '/team/details',
    '/team/reports',
    '/members',
    '/settings/account',
    '/settings/appearance',
    '/settings/rules',
    '/settings/models',
    '/settings/usage',
    '/settings/support',
  ])
  if (known.has(pathname)) return pathname
  const match = pathname.match(/^\/(assistant|work|reports|messages|team)\/[^/]+$/)
  return match ? `/${match[1]}/${match[1] === 'assistant' ? ':conversationId' : ':id'}` : null
}
export function captureDiagnostics(): SupportDiagnostics {
  const agent = typeof navigator === 'undefined' ? '' : navigator.userAgent
  const browser = agent.match(/(Firefox|Edg|Chrome|CriOS|FxiOS)\/([\d.]+)/)
  const safari = agent.match(/Version\/([\d.]+).*Safari/)
  const os = agent.match(/(Windows NT|Android|iPhone OS|CPU OS|Mac OS X) ([\d._]+)/)
  return {
    occurredAt: new Date().toISOString(),
    page: diagnosticPage(typeof window === 'undefined' ? '' : (window.location?.pathname ?? '')),
    appVersion: null,
    category: 'unknown',
    httpStatus: null,
    requestId: null,
    browser: browser
      ? `${({ Edg: 'Edge', CriOS: 'Chrome', FxiOS: 'Firefox' } as Record<string, string>)[browser[1]] ?? browser[1]} ${browser[2]}`
      : safari
        ? `Safari ${safari[1]}`
        : null,
    os: os
      ? `${({ 'Windows NT': 'Windows', Android: 'Android', 'iPhone OS': 'iOS', 'CPU OS': 'iPadOS', 'Mac OS X': 'macOS' } as Record<string, string>)[os[1]]} ${os[2].replaceAll('_', '.')}`
      : null,
    viewport: typeof window === 'undefined' ? null : `${window.innerWidth}x${window.innerHeight}`,
  }
}
export const diagnosticText = (value: SupportDiagnostics) =>
  Object.entries({
    发生时间: value.occurredAt,
    前端版本: value.appVersion,
    页面: value.page,
    错误分类: value.category,
    HTTP状态: value.httpStatus,
    请求编号: value.requestId,
    浏览器: value.browser,
    系统: value.os,
    视口: value.viewport,
  })
    .map(([key, item]) => `${key}：${item ?? '未知'}`)
    .join('\n')

export async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      /* HTTP/focus fallback. */
    }
  }
  const input = document.createElement('textarea')
  input.value = value
  input.style.position = 'fixed'
  input.style.opacity = '0'
  document.body.append(input)
  input.select()
  const copied = document.execCommand('copy')
  input.remove()
  if (!copied) throw new Error('无法自动复制，请选中下方文字手动复制。')
}
