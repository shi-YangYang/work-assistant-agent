import type { Location } from 'react-router'

export type ReturnPoint = { path: string; state: unknown; label: string }
const localPage =
  /^\/(?:assistant(?:\/[^/?#\\]+)?|work(?:\/[^/?#\\]+)?|reports(?:\/[^/?#\\]+)?|messages\/[^/?#\\]+|team(?:\/[^/?#\\]+)?|members)(?:\?[^#\\]*)?$/

export function pageName(path: string) {
  const pathname = path.split('?')[0]
  if (pathname.startsWith('/assistant/')) return '会话'
  if (pathname.startsWith('/messages/')) return '原始上报'
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

export function detailReturn(path: string, state: unknown): ReturnPoint {
  const point = returnPoint(state)
  if (point && point.path.split('?')[0] !== path) return point
  const fallback = path.startsWith('/team/')
    ? '/team'
    : path.startsWith('/work/')
      ? '/work'
      : path.startsWith('/reports/')
        ? '/reports'
        : '/assistant'
  return { path: fallback, state: null, label: pageName(fallback) }
}

export function detailContext(state: unknown) {
  let point = returnPoint(state)
  for (let depth = 0; point && depth < 12; depth++) {
    if (point.path.startsWith('/team')) return '团队看板'
    point = returnPoint(point.state)
  }
  return '工作空间'
}

export function breadcrumbPoints(path: string, state: unknown): ReturnPoint[] {
  const points: ReturnPoint[] = [{ path, state, label: pageName(path) }]
  const seen = new Set([path.split('?')[0]])
  let parent = returnPoint(state)
  for (let depth = 0; parent && depth < 8; depth++) {
    const key = parent.path.split('?')[0]
    if (seen.has(key)) break
    seen.add(key)
    points.unshift(parent)
    parent = returnPoint(parent.state)
  }
  // Only ancestors with decreasing business hierarchy can become breadcrumbs;
  // switching between peers must never grow a click-history chain.
  const rank = (value: string) =>
    value.startsWith('/messages/')
      ? 5
      : value.startsWith('/work/')
        ? 4
        : value.startsWith('/reports/')
          ? 3
          : value.startsWith('/team/') || value.startsWith('/assistant/')
            ? 2
            : 1
  return points.filter(
    (point, index) =>
      index === points.length - 1 || rank(point.path) < rank(points[index + 1].path),
  )
}
