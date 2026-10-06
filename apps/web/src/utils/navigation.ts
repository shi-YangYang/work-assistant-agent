import type { Location } from 'react-router'

export type ReturnPoint = { path: string; state: unknown; label: string }

const localPage =
  /^\/(?:assistant(?:\/[^/?#\\]+)?|work(?:\/[^/?#\\]+)?|reports(?:\/[^/?#\\]+)?|messages\/[^/?#\\]+|team(?:\/[^/?#\\]+)?|members)(?:\?[^#\\]*)?$/

export function pageName(path: string) {
  const pathname = path.split('?')[0]
  if (pathname.startsWith('/assistant/')) return '会话'
  if (pathname.startsWith('/messages/')) return '原始上报'
  if (pathname === '/team/reports') return '汇报情况'
  if (pathname === '/team/details') return '统计明细'
  if (pathname.startsWith('/team/')) return '员工详情'
  if (pathname.startsWith('/work/')) return '工作详情'
  if (pathname.startsWith('/reports/')) return '报告详情'
  return (
    {
      '/assistant': '工作助手',
      '/work': '我的工作',
      '/reports': '我的报告',
      '/team': '团队看板',
      '/members': '成员管理',
    }[pathname] ?? '工作空间'
  )
}

export function detailState(location: Pick<Location, 'pathname' | 'search' | 'state'>) {
  return {
    returnTo: {
      path: location.pathname + location.search,
      state: location.state,
      label: pageName(location.pathname),
    },
  }
}

function returnPoint(state: unknown): ReturnPoint | null {
  if (!state || typeof state !== 'object' || !('returnTo' in state)) return null
  const point = state.returnTo
  if (
    !point ||
    typeof point !== 'object' ||
    !('path' in point) ||
    typeof point.path !== 'string' ||
    !localPage.test(point.path)
  )
    return null
  return {
    path: point.path,
    state: 'state' in point ? point.state : null,
    label: pageName(point.path),
  }
}

export function detailReturn(
  path: string,
  state: unknown,
  defaultPoint?: ReturnPoint,
): ReturnPoint {
  const point = returnPoint(state)
  if (point && point.path.split('?')[0] !== path) return point
  if (defaultPoint) return defaultPoint
  const fallback = path.startsWith('/team/')
    ? '/team'
    : path.startsWith('/work/')
      ? '/work'
      : path.startsWith('/reports/')
        ? '/reports'
        : '/assistant'
  return { path: fallback, state: null, label: pageName(fallback) }
}
