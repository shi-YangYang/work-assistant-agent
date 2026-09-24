import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { expect, it } from 'vitest'
import { ApiError } from '../../apps/web/src/api/client'
import { ErrorNotice } from '../../apps/web/src/components/ErrorNotice'
import { ErrorDiagnostics, SupportLink } from '../../apps/web/src/lib/support-link'

function render(error: Error | string, diagnostics = false, retry?: () => void) {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(
        SupportLink.Provider,
        { value: '/settings/support' },
        createElement(
          ErrorDiagnostics.Provider,
          { value: diagnostics },
          createElement(ErrorNotice, { children: error, retry }),
        ),
      ),
    ),
  )
}

it('shows an ordinary error without diagnostic controls by default, including outside the router', () => {
  const error = new ApiError(500, 'unavailable', '服务暂时不可用', 'server', 'request-123')
  for (const html of [
    render(error),
    renderToStaticMarkup(createElement(ErrorNotice, { children: error })),
  ]) {
    expect(html).toContain('role="alert"')
    expect(html).toContain('服务暂时不可用')
    expect(html).not.toMatch(/请求编号|诊断|问题反馈|notice-actions/)
  }
})

it('keeps diagnostic details and feedback available when the assistant page enables them', () => {
  const error = new ApiError(500, 'unavailable', '服务暂时不可用', 'server', 'request-123')
  const html = render(error, true)
  expect(html).toContain('请求编号：request-123')
  expect(html).toContain('复制诊断摘要')
  expect(html).toContain('href="/settings/support"')
  expect(render('发送失败，请重试。', true)).toContain('复制诊断摘要')
})

it('preserves retry limits and permission/cancellation handling in both display modes', () => {
  for (const diagnostics of [false, true]) {
    const html = render(
      new ApiError(429, 'too_many_requests', '请求较多，请稍后再试。', 'rate_limited', null, 30),
      diagnostics,
      () => undefined,
    )
    expect(html).toContain('disabled=""')
    expect(html).toContain('30 秒后重试')
    const forbidden = render(
      new ApiError(403, 'forbidden', '没有访问权限', 'forbidden'),
      diagnostics,
      () => undefined,
    )
    expect(forbidden).toContain('没有访问权限')
    expect(forbidden).not.toContain('重试')
    expect(render(new ApiError(0, 'cancelled', '', 'cancelled'), diagnostics)).toBe('')
    expect(render('', diagnostics)).toBe('')
  }
})
