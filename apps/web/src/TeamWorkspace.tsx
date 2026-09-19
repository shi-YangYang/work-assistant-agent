import { useEffect } from 'react'
import { Navigate, useLocation, useParams, useSearchParams } from 'react-router'
import {
  ArrowLeft,
  ArrowRight,
  BriefcaseBusiness,
  ChevronRight,
  ClipboardCheck,
  RefreshCw,
  Search,
} from 'lucide-react'
import type { TeamReportRow, TeamWorkRow, TeamWorkspacePage } from '@paa/api-contracts'
import { dateLabel, useResource } from './api'
import { Pagination, PeriodFilter, RecordEmpty } from './ListControls'
import { ErrorNotice, Modal, Status } from './ui'
import { WorkDetail, ReportDetail } from './Records'
import { obligationLabel } from './ReportObligations'

type Row = TeamWorkRow | TeamReportRow
const isWork = (row: Row): row is TeamWorkRow => 'work' in row

export function TeamWorkspace() {
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const view = params.get('view') === 'reports' ? 'reports' : 'work'
  const scope = params.get('scope') === 'updated' ? 'updated' : 'current'
  const kind = params.get('kind') === 'weekly' ? 'weekly' : 'daily'
  const status = params.get(`${view}Status`) || ''
  const offset = Math.max(0, Number(params.get(`${view}Offset`)) || 0)
  const query = new URLSearchParams({ scope, kind, status, offset: String(offset) })
  for (const key of ['q', 'member', 'members', 'period', 'start', 'end']) {
    if (params.get(key)) query.set(key, params.get(key)!)
  }
  const list = useResource<TeamWorkspacePage<Row>>(`/team/workspace/${view}?${query}`, 30000)
  const update = (values: Record<string, string>, reset = true) => {
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
    <div className="page team-workspace">
      <div className="page-heading records-heading">
        <h2>团队看板</h2>
        <button
          className="icon-button"
          aria-label="刷新团队看板"
          title="刷新"
          onClick={list.refresh}
        >
          <RefreshCw size={18} />
        </button>
      </div>
      <section className="records-panel team-panel">
        <div className="team-view-heading">
          <div className="tabs" aria-label="看板视图">
            <button
              className={view === 'work' ? 'active' : ''}
              aria-pressed={view === 'work'}
              onClick={() => update({ view: 'work' }, false)}
            >
              <BriefcaseBusiness size={17} />
              工作进展
            </button>
            <button
              className={view === 'reports' ? 'active' : ''}
              aria-pressed={view === 'reports'}
              onClick={() => update({ view: 'reports' }, false)}
            >
              <ClipboardCheck size={17} />
              日报周报
            </button>
          </div>
          <div className="segmented-control" aria-label={view === 'work' ? '工作范围' : '报告类型'}>
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
                className={(view === 'work' ? scope : kind) === value ? 'active' : ''}
                aria-pressed={(view === 'work' ? scope : kind) === value}
                onClick={() => update({ [view === 'work' ? 'scope' : 'kind']: value })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="team-toolbar">
          <div className="work-search">
            <Search size={17} aria-hidden="true" />
            <input
              type="search"
              aria-label="搜索团队内容"
              placeholder="搜索员工或内容"
              value={params.get('q') || ''}
              onChange={(e) => update({ q: e.target.value })}
            />
          </div>
          <select
            aria-label="选择员工"
            value={params.get('member') || ''}
            onChange={(e) => update({ member: e.target.value })}
          >
            <option value="">全部员工</option>
            {data?.members.map((member) => (
              <option key={member.id} value={member.id}>
                {member.name}
              </option>
            ))}
          </select>
          <select
            aria-label="员工范围"
            value={params.get('members') || 'active'}
            onChange={(e) => update({ members: e.target.value, member: '' })}
          >
            <option value="active">在职员工</option>
            <option value="inactive">停用员工</option>
            <option value="all">全部员工</option>
          </select>
          {(view === 'reports' || scope === 'updated') && (
            <PeriodFilter params={params} range={data?.range} change={update} />
          )}
        </div>
        <div className="team-counts" aria-label={view === 'work' ? '工作状态筛选' : '汇报状态筛选'}>
          {metrics.map(([value, label, key]) => (
            <button
              key={key}
              aria-pressed={status === value}
              className={status === value ? 'selected' : ''}
              onClick={() => update({ [`${view}Status`]: value })}
            >
              <span>{label}</span>
              <strong>{data?.counts[key] ?? '—'}</strong>
            </button>
          ))}
        </div>
        <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
        <div className="team-results">
          {!data && !list.error && (
            <p className="records-loading" role="status">
              正在读取团队记录…
            </p>
          )}
          {data && (
            <div className="team-result-caption">
              <span>
                {view === 'work'
                  ? scope === 'current'
                    ? '当前工作状态'
                    : '期间更新 · 截至所选期末的状态'
                  : '所选周期的汇报'}{' '}
                · {data.total} 条
              </span>
              {(params.get('q') || params.get('member') || status) && (
                <button
                  className="text-button"
                  onClick={() => update({ q: '', member: '', [`${view}Status`]: '' })}
                >
                  清除筛选
                </button>
              )}
            </div>
          )}
          {data?.items.length ? (
            <div className="team-records">
              {data.items.map((row) => (
                <div className="team-record" key={row.id}>
                  <button
                    className="team-member"
                    title={`只看${row.member.name}`}
                    onClick={() => update({ member: row.member.id })}
                  >
                    <span className="avatar">{row.member.name.slice(0, 1)}</span>
                    <span>
                      {row.member.name}
                      {!row.member.active && (
                        <small>{row.member.deleted ? '账号已删除' : '已停用'}</small>
                      )}
                    </span>
                  </button>
                  {isWork(row) ? (
                    <button className="team-record-content" onClick={() => open(row)}>
                      <div className="team-record-title">
                        <h3>{row.work.title}</h3>
                        <Status value={row.work.status} />
                      </div>
                      <p>{row.work.summary || '暂无工作说明'}</p>
                      {row.work.blocker && row.work.status !== 'done' && (
                        <small className="team-blocker">阻碍：{row.work.blocker}</small>
                      )}
                      <div className="team-record-meta">
                        <span>
                          {scope === 'updated' ? '更新于' : '最近更新'}{' '}
                          {dateLabel(row.work.updatedAt)}
                        </span>
                        {row.work.dueDate && <span>截止 {row.work.dueDate}</span>}
                        <span className="team-read">
                          查看工作
                          <ChevronRight size={15} />
                        </span>
                      </div>
                    </button>
                  ) : (
                    <div className="team-report-content">
                      <div className="team-record-title">
                        <h3>
                          {row.period}
                          {row.kind === 'weekly' ? ` — ${row.periodEnd}` : ''}
                          <small>{row.kind === 'daily' ? '日报' : '周报'}</small>
                        </h3>
                        <span className={`status ${row.state}`}>{obligationLabel(row.state)}</span>
                      </div>
                      <p>
                        {row.summary ||
                          (row.state === 'cancelled' ? '该周期的汇报安排已撤销' : '尚未提交报告')}
                      </p>
                      <div className="team-record-meta">
                        <span>
                          {row.submittedAt
                            ? `提交于 ${dateLabel(row.submittedAt)}`
                            : row.deadlineAt
                              ? `截止 ${new Intl.DateTimeFormat('zh-CN', { timeZone: row.timezone, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(row.deadlineAt))}`
                              : ''}
                        </span>
                        {!row.scheduled && row.reportId && <span>自主提交</span>}
                        {row.reportId && (
                          <button className="text-button team-read" onClick={() => open(row)}>
                            查看报告
                            <ChevronRight size={15} />
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            data && (
              <RecordEmpty
                icon={
                  view === 'work' ? <BriefcaseBusiness size={27} /> : <ClipboardCheck size={27} />
                }
                title={view === 'work' ? '暂无符合条件的工作' : '暂无符合条件的汇报'}
              >
                {view === 'work'
                  ? '员工创建或确认工作后，会显示在这里。'
                  : '可以调整日期，查看其他周期的汇报安排与已提交报告。'}
              </RecordEmpty>
            )
          )}
        </div>
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
        <Modal
          className="team-detail-drawer"
          title={view === 'work' ? '工作详情' : '报告详情'}
          onClose={close}
        >
          <div className="team-reader-nav">
            <span>
              {index >= 0
                ? `${readable[index].member.name} · 本页 ${index + 1} / ${readable.length}`
                : '详情'}
            </span>
            <div className="inline">
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
          {view === 'work' ? (
            <WorkDetail
              key={`${selected}:${params.get('revision')}`}
              recordId={selected}
              recordSearch={params.get('revision') ? `?revision=${params.get('revision')}` : ''}
            />
          ) : (
            <ReportDetail
              key={`${selected}:${params.get('revision')}`}
              recordId={selected}
              onRecordDeleted={() => {
                list.refresh()
                close()
              }}
              recordSearch={params.get('revision') ? `?revision=${params.get('revision')}` : ''}
            />
          )}
        </Modal>
      )}
    </div>
  )
}

// Existing bookmarks and source links keep working, but enter the same workspace.
export function TeamLegacyRedirect() {
  const location = useLocation()
  const { id } = useParams()
  const params = new URLSearchParams(location.search)
  const reports =
    location.pathname === '/team/reports' ||
    params.get('tab') === 'reports' ||
    params.get('metric') === 'reports'
  params.set('view', reports ? 'reports' : 'work')
  if (id) params.set('member', id)
  if (params.get('metric') === 'blocked') params.set('workStatus', 'blocked')
  if (/^\d{4}-\d{2}-\d{2}$/.test(params.get('period') || '')) {
    params.set('start', params.get('period')!)
    params.set('end', params.get('period')!)
    params.set('period', 'custom')
  }
  params.delete('tab')
  params.delete('metric')
  return <Navigate to={`/team?${params}`} replace />
}
