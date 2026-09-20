import { Modal } from '@web/components/Modal'
import {
  readConversationForBreadcrumb,
  readMessageForBreadcrumb,
} from '@web/features/assistant/api/requests'
import { readReportForBreadcrumb } from '@web/features/reports/api/requests'
import { readMemberForBreadcrumb } from '@web/features/team/api/requests'
import { readWorkForBreadcrumb } from '@web/features/work/api/requests'

import { useWorkspace } from '@web/lib/workspace'
import type { ReturnPoint } from '@web/utils/navigation'
import { breadcrumbPoints, pageName } from '@web/utils/navigation'
import { ArrowLeft, ChevronRight, MoreHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router'

export function Breadcrumbs() {
  const location = useLocation()
  const { identity } = useWorkspace()
  const [loaded, setLoaded] = useState<{ path: string; points: ReturnPoint[] } | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [revision, setRevision] = useState(0)
  const path = location.pathname + location.search
  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1)
    window.addEventListener('paa-record-updated', refresh)
    return () => window.removeEventListener('paa-record-updated', refresh)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    const resolve = async (point: ReturnPoint) => {
      const [section, id] = point.path.split('?')[0].split('/').slice(1)
      let ownerId: string | undefined
      let conversationId: string | null | undefined
      let label = pageName(point.path)
      if (id && !['details', 'reports'].includes(id) && section === 'team')
        label = (await readMemberForBreadcrumb(id, { signal: controller.signal })).member.name
      if (id && section === 'assistant')
        label = (await readConversationForBreadcrumb(id, { signal: controller.signal })).title
      if (id && section === 'work') {
        const item = await readWorkForBreadcrumb(id, { signal: controller.signal })
        label = item.title
        ownerId = item.ownerId
      }
      if (id && section === 'reports') {
        const item = await readReportForBreadcrumb(id, { signal: controller.signal })
        label = item.period + (item.kind === 'daily' ? '日报' : '周报')
        ownerId = item.ownerId
      }
      if (id && section === 'messages') {
        const item = await readMessageForBreadcrumb(id, { signal: controller.signal })
        ownerId = item.ownerId
        conversationId = item.conversationId
      }
      return { ...point, label, ownerId, conversationId }
    }
    void (async () => {
      if (location.pathname.startsWith('/settings/')) {
        const name =
          {
            account: '账户',
            appearance: '外观',
            rules: '汇报规则',
            login: '登录方式',
            models: '模型服务管理',
            usage: '模型用量',
            support: '问题反馈',
            voiceprints: '公司声纹',
          }[location.pathname.split('/')[2]] ?? '设置'
        setLoaded({
          path,
          points: [
            { path: '/settings/account', state: null, label: '设置' },
            { path, state: null, label: name },
          ],
        })
        return
      }
      const raw = breadcrumbPoints(path, location.state)
      const resolved = await Promise.all(
        raw.map(async (point) => {
          try {
            return await resolve(point)
          } catch {
            return null
          }
        }),
      )
      const points = resolved.filter((point): point is NonNullable<typeof point> => !!point)
      const current = points.find((point) => point.path === path)
      if (!current) {
        if (!controller.signal.aborted)
          setLoaded({ path, points: [{ path, state: null, label: pageName(path) }] })
        return
      }
      if (points.length === 1 && location.pathname.split('/').length > 2) {
        const add = async (url: string) => {
          try {
            return await resolve({ path: url, state: null, label: pageName(url) })
          } catch {
            return null
          }
        }
        if (
          current.ownerId &&
          current.ownerId !== identity.member.id &&
          identity.member.role === 'admin'
        ) {
          const member = await add(`/team/${current.ownerId}`)
          if (member)
            points.unshift(
              {
                path: '/team',
                state: null,
                label: '团队看板',
                ownerId: undefined,
                conversationId: undefined,
              },
              member,
            )
        } else if (location.pathname.startsWith('/team/')) {
          points.unshift({ ...current, path: '/team', state: null, label: '团队看板' })
        } else if (location.pathname.startsWith('/messages/') && current.conversationId) {
          const conversation = await add(`/assistant/${current.conversationId}`)
          points.unshift(
            { ...current, path: '/assistant', state: null, label: '工作助手' },
            ...(conversation ? [conversation] : []),
          )
        } else {
          const base = '/' + location.pathname.split('/')[1]
          points.unshift({ ...current, path: base, state: null, label: pageName(base) })
        }
      }
      // If the supplied chain starts on a detail, restore its semantic root.
      const first = points[0]
      if (first.path.startsWith('/assistant/'))
        points.unshift({ ...first, path: '/assistant', state: null, label: '工作助手' })
      if (!controller.signal.aborted) setLoaded({ path, points })
    })()
    return () => controller.abort()
  }, [path, location.pathname, location.state, identity.member.id, identity.member.role, revision])
  const points =
    loaded?.path === path ? loaded.points : [{ path, state: null, label: pageName(path) }]
  return (
    <nav className="breadcrumbs" aria-label="面包屑">
      {points.length > 1 && !location.pathname.startsWith('/settings/') && (
        <Link
          className="icon-button"
          aria-label={`返回${points[points.length - 2].label}`}
          title={`返回${points[points.length - 2].label}`}
          to={points[points.length - 2].path}
          state={points[points.length - 2].state}
        >
          <ArrowLeft size={18} />
        </Link>
      )}
      {points.map((point, index) => (
        <span
          key={`${index}:${point.path}`}
          className={index > 0 && index < points.length - 1 ? 'breadcrumb-middle' : ''}
        >
          {index > 0 && <ChevronRight size={13} aria-hidden="true" />}
          {index === points.length - 1 ? (
            <strong aria-current="page" title={point.label}>
              {point.label}
            </strong>
          ) : (
            <Link to={point.path} state={point.state} title={point.label}>
              {point.label}
            </Link>
          )}
        </span>
      ))}
      {points.length > 2 && (
        <button
          className="icon-button breadcrumb-overflow"
          aria-label="查看完整页面路径"
          onClick={() => setExpanded(true)}
        >
          <MoreHorizontal size={16} />
        </button>
      )}
      {expanded && (
        <Modal title="页面路径" onClose={() => setExpanded(false)}>
          <nav className="breadcrumb-path">
            {points.map((point, index) =>
              index === points.length - 1 ? (
                <strong aria-current="page" key={`${index}:${point.path}`}>
                  {point.label}
                </strong>
              ) : (
                <Link
                  key={`${index}:${point.path}`}
                  to={point.path}
                  state={point.state}
                  onClick={() => setExpanded(false)}
                >
                  {point.label}
                </Link>
              ),
            )}
          </nav>
        </Modal>
      )}
    </nav>
  )
}
