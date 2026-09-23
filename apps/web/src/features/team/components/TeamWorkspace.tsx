import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import teamStyles from '../styles/team.module.css'
import type { TeamWorkspacePage } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { Pagination } from '@web/components/Pagination'
import { teamWorkspacePath } from '@web/features/team/api/requests'
import { TeamFilters } from '@web/features/team/components/TeamFilters'
import { TeamResults } from '@web/features/team/components/TeamResults'
import { isWork, type TeamRow as Row } from '@web/features/team/types'
import { useResource } from '@web/hooks/useResource'
import { ArrowLeft, ArrowRight, BriefcaseBusiness, ClipboardCheck, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router'

export function TeamWorkspace({
  renderDetail,
}: {
  renderDetail: (
    view: 'work' | 'reports',
    id: string,
    revision: string | null,
    onDeleted: () => void,
  ) => React.ReactNode
}) {
  const [searchReset, resetSearch] = useState(0)
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const view = params.get('view') === 'reports' ? 'reports' : 'work'
  const scope = params.get('scope') === 'updated' ? 'updated' : 'current'
  const kind = params.get('kind') === 'weekly' ? 'weekly' : 'daily'
  const status = params.get(`${view}Status`) || ''
  const offset = Math.max(0, Number(params.get(`${view}Offset`)) || 0)
  const query = new URLSearchParams({ scope, kind, status, offset: String(offset) })
  for (const key of ['q', 'member', 'members', 'period', 'start', 'end']) {
    if (view === 'work' && scope === 'current' && ['period', 'start', 'end'].includes(key)) continue
    if (params.get(key)) query.set(key, params.get(key)!)
  }
  const list = useResource<TeamWorkspacePage<Row>>(teamWorkspacePath(view, query), 30000)
  const update = (values: Record<string, string>, reset = true) => {
    if (values.q === '') resetSearch((value) => value + 1)
    const next = new URLSearchParams(params)
    if (reset) {
      next.delete('workOffset')
      next.delete('reportsOffset')
    }
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace: true, state: location.state })
  }
  const data = list.data
  useEffect(() => {
    if (data && !data.items.length && offset > 0) {
      const next = new URLSearchParams(params)
      next.set(`${view}Offset`, String(Math.max(0, offset - 20)))
      setParams(next, { replace: true, state: location.state })
    }
  }, [data, offset, params, setParams, view, location.state])
  const readable = data?.items.filter((row) => isWork(row) || row.reportId) ?? []
  const selected = params.get('record')
  const index = readable.findIndex((row) => (isWork(row) ? row.id : row.reportId) === selected)
  const open = (row: Row, replace = false) => {
    const next = new URLSearchParams(params)
    const revision = isWork(row) ? (row.work.historical ? row.work.revision : null) : row.revision
    next.set('record', (isWork(row) ? row.id : row.reportId)!)
    if (revision) next.set('revision', String(revision))
    else next.delete('revision')
    setParams(next, { replace, state: location.state })
  }
  const close = () => update({ record: '', revision: '' }, false)
  const metrics =
    view === 'work'
      ? [
          ['', '全部工作', 'all'],
          ['in_progress', '未完成', 'in_progress'],
          ['blocked', '有阻碍', 'blocked'],
          ['done', '已完成', 'done'],
        ]
      : [
          ['', '全部汇报', 'all'],
          ['expected', '应提交', 'expected'],
          ['submitted', '已提交', 'submitted'],
          ['pending', '未提交', 'pending'],
          ['overdue', '已逾期', 'overdue'],
          ['cancelled', '已撤销', 'cancelled'],
        ]
  return (
    <div className={layoutStyles['page']} data-scroll-container>
      <div className={layoutStyles['page-heading']}>
        <div>
          <h2>团队看板</h2>
          <p>看见团队的每一步，让需要关注的事更清晰。</p>
        </div>
        <button
          className={controlsStyles['icon-button']}
          aria-label="刷新团队看板"
          title="刷新"
          onClick={list.refresh}
        >
          <RefreshCw size={18} />
        </button>
      </div>
      <div
        className={teamStyles['team-counts']}
        data-view={view}
        aria-label={view === 'work' ? '工作状态筛选' : '汇报状态筛选'}
      >
        {metrics.map(([value, label, key]) => (
          <button
            key={key}
            aria-pressed={status === value}
            data-selected={status === value}
            onClick={() => update({ [`${view}Status`]: value })}
          >
            <span>{label}</span>
            <strong>{data?.counts[key] ?? '—'}</strong>
          </button>
        ))}
      </div>
      <section className={teamStyles['team-panel']}>
        <div className={teamStyles['team-view-heading']}>
          <div
            className={`${layoutStyles['tabs']} ${teamStyles['slot-tabs']}`}
            aria-label="看板视图"
          >
            <button
              data-active={view === 'work'}
              aria-pressed={view === 'work'}
              onClick={() => update({ view: 'work' }, false)}
            >
              <BriefcaseBusiness size={17} />
              工作进展
            </button>
            <button
              data-active={view === 'reports'}
              aria-pressed={view === 'reports'}
              onClick={() => update({ view: 'reports' }, false)}
            >
              <ClipboardCheck size={17} />
              日报周报
            </button>
          </div>
          <div
            className={teamStyles['segmented-control']}
            aria-label={view === 'work' ? '工作范围' : '报告类型'}
          >
            {(view === 'work'
              ? [
                  ['current', '当前工作'],
                  ['updated', '期间更新'],
                ]
              : [
                  ['daily', '日报'],
                  ['weekly', '周报'],
                ]
            ).map(([value, label]) => (
              <button
                key={value}
                data-active={(view === 'work' ? scope : kind) === value}
                aria-pressed={(view === 'work' ? scope : kind) === value}
                onClick={() => update({ [view === 'work' ? 'scope' : 'kind']: value })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <TeamFilters
          params={params}
          update={update}
          searchReset={searchReset}
          data={data}
          view={view}
          scope={scope}
        />
        <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
        <TeamResults
          data={data}
          list={list}
          view={view}
          scope={scope}
          params={params}
          status={status}
          update={update}
          open={open}
        />
        {(offset > 0 || data?.nextCursor) && (
          <Pagination
            page={Math.floor(offset / 20) + 1}
            hasNext={!!data?.nextCursor}
            previous={() => update({ [`${view}Offset`]: String(Math.max(0, offset - 20)) }, false)}
            next={() => update({ [`${view}Offset`]: data!.nextCursor! }, false)}
          />
        )}
      </section>
      {selected && (
        <Modal variant="drawer" title={view === 'work' ? '工作详情' : '报告详情'} onClose={close}>
          <div className={teamStyles['team-reader-nav']}>
            <span>
              {index >= 0
                ? `${readable[index].member.name} · 本页 ${index + 1} / ${readable.length}`
                : '详情'}
            </span>
            <div className={layoutStyles['inline']}>
              <button
                aria-label="上一条记录"
                disabled={index <= 0}
                onClick={() => open(readable[index - 1], true)}
              >
                <ArrowLeft size={16} />
                上一条
              </button>
              <button
                aria-label="下一条记录"
                disabled={index < 0 || index >= readable.length - 1}
                onClick={() => open(readable[index + 1], true)}
              >
                下一条
                <ArrowRight size={16} />
              </button>
            </div>
          </div>
          {renderDetail(view, selected, params.get('revision'), () => {
            list.refresh()
            close()
          })}
        </Modal>
      )}
    </div>
  )
}
