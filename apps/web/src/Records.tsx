import { ReportObligations } from './ReportObligations'
import { useCursorPage } from './list-state'
import { Pagination, RecordEmpty, WorkFilters } from './ListControls'
import { BusinessSources } from './BusinessSources'
import { DeleteRecord, ReportActions } from './RecordManagement'
import { timezoneLabel } from './timezones'
import { usePagedResource } from './paged-resource'
import { useState } from 'react'
import { Link, Navigate, useNavigate, useLocation, useParams, useSearchParams } from 'react-router'
import {
  CalendarDays,
  ChevronRight,
  ClipboardList,
  RefreshCw,
  FileText,
  Plus,
  Sparkles,
} from 'lucide-react'
import type { Progress, Report, ReportContent, Rules, Work } from '@paa/api-contracts'
import { api, dateLabel, todayIn, useResource, write } from './api'
import { useWorkspace } from './workspace'
import {
  AutoTextarea,
  ConflictRecovery,
  Actions,
  BusyButton,
  ErrorNotice,
  Modal,
  Status,
} from './ui'
import { JobNotice, ProgressFields } from './Assistant'
import { detailReturn, detailState } from './navigation'

export function WorkList({
  items,
  own = false,
  refresh,
}: {
  items: Work[]
  own?: boolean
  refresh: () => void
}) {
  const [editing, setEditing] = useState<Work | null>(null)
  const [deleting, setDeleting] = useState<Work | null>(null)
  const location = useLocation()
  return (
    <div className="record-list">
      {items.map((work) => (
        <div className="record-row work-row" key={work.id}>
          <Link
            className="record-main"
            to={`/work/${work.id}${work.historical ? `?revision=${work.revision}` : ''}`}
            state={detailState(location)}
          >
            <div className="row-between">
              <h3>{work.title}</h3>
              <Status value={work.status} />
            </div>
            <p className="record-summary">{work.summary}</p>
            {work.dueDate && <small className="record-note">截止 {work.dueDate}</small>}
            {(work.blocker || work.nextStep) && (
              <small className={`record-note ${work.blocker ? 'work-blocker' : ''}`}>
                {work.blocker ? `阻碍：${work.blocker}` : `下一步：${work.nextStep}`}
              </small>
            )}
          </Link>
          <time className="record-updated">{dateLabel(work.updatedAt)}</time>
          {own ? (
            <Actions>
              <button role="menuitem" onClick={() => setEditing(work)}>
                编辑工作
              </button>
              <button role="menuitem" className="danger" onClick={() => setDeleting(work)}>
                删除工作
              </button>
            </Actions>
          ) : (
            <ChevronRight size={18} />
          )}
        </div>
      ))}
      {deleting && (
        <DeleteRecord
          kind="work-items"
          id={deleting.id}
          title={deleting.title}
          revision={deleting.revision}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null)
            refresh()
          }}
        />
      )}
      {editing && (
        <WorkEditor
          work={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}
export function WorkPage() {
  const [creating, setCreating] = useState(false)
  const [search] = useSearchParams()
  const query = search.get('q') ?? ''
  const status = search.get('status') ?? ''
  const list = useCursorPage<Work>(`/work-items?${new URLSearchParams({ q: query, status })}`)
  return (
    <div className="page records-page work-page">
      <div className="page-heading">
        <h2>我的工作</h2>
        <div className="card-actions">
          <button
            className="icon-button"
            aria-label="刷新工作"
            title="刷新工作"
            onClick={list.refresh}
          >
            <RefreshCw size={16} />
          </button>
          <button className="primary" onClick={() => setCreating(true)}>
            <Plus size={16} />
            新建工作
          </button>
        </div>
      </div>
      {creating && (
        <CreateWork
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false)
            list.refresh()
          }}
        />
      )}
      <div className="records-surface">
        <div className="records-toolbar">
          <WorkFilters query={query} status={status} change={list.filter} />
        </div>
        <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
        <div className="records-results" aria-label="工作列表">
          {!list.data && !list.error && (
            <p className="records-loading" role="status">
              正在读取工作…
            </p>
          )}
          {list.data &&
            (list.data.items.length ? (
              <WorkList items={list.data.items} own refresh={list.refresh} />
            ) : (
              <RecordEmpty
                icon={<ClipboardList size={27} />}
                title={query || status ? '没有符合条件的工作' : '还没有工作'}
                action={
                  query || status ? (
                    <button onClick={() => list.filter({ q: '', status: '' })}>重置筛选</button>
                  ) : (
                    <>
                      <button className="primary" onClick={() => setCreating(true)}>
                        <Plus size={16} />
                        创建第一项工作
                      </button>
                      <Link to="/assistant">
                        前往工作助手
                        <ChevronRight size={15} />
                      </Link>
                    </>
                  )
                }
              >
                {query || status
                  ? '换个关键词，或清除筛选条件。'
                  : '记录一项工作，随时跟进进展与下一步。'}
              </RecordEmpty>
            ))}
        </div>
        {list.data && (list.page > 1 || list.data.nextCursor) && (
          <Pagination
            page={list.page}
            hasNext={!!list.data.nextCursor}
            previous={list.previous}
            next={list.next}
          />
        )}
      </div>
    </div>
  )
}
function CreateWork({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { drafts, setDraft } = useWorkspace()
  const draft = drafts['work:new'] as { content: Progress; key: string } | undefined
  const [initialKey] = useState(() => crypto.randomUUID())
  const content = draft?.content ?? {
    title: '',
    summary: '',
    status: 'in_progress' as const,
    blocker: '',
    nextStep: '',
    dueDate: null,
  }
  const key = draft?.key ?? initialKey
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  return (
    <Modal title="新建工作" onClose={() => !busy && onClose()}>
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          setBusy(true)
          setError('')
          // Preserve the same key through an uncertain network response and reopening.
          setDraft('work:new', { content, key })
          try {
            await write('/work-items', content, 'POST', key)
            setDraft('work:new', undefined)
            window.dispatchEvent(new Event('paa-record-updated'))
            onSaved()
          } catch (error) {
            setError(error as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        <fieldset disabled={busy}>
          <ProgressFields
            value={content}
            change={(value) => setDraft('work:new', { content: value, key: crypto.randomUUID() })}
          />
        </fieldset>
        <ErrorNotice>{error}</ErrorNotice>
        <div className="form-actions">
          <button type="button" disabled={busy} onClick={onClose}>
            稍后继续
          </button>
          <BusyButton busy={busy} className="primary">
            创建工作
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
function WorkEditor({
  work,
  onClose,
  onSaved,
}: {
  work: Work
  onClose: () => void
  onSaved: () => void
}) {
  const { drafts, setDraft } = useWorkspace()
  const key = `work:${work.id}`
  const stored = drafts[key] as { content: Progress; revision: number } | undefined
  const value = stored?.content ?? work
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  return (
    <Modal title="更正工作进展" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          try {
            const { title, summary, status, blocker, nextStep, dueDate } = value
            await write(`/work-items/${work.id}/progress`, {
              title,
              summary,
              status,
              blocker,
              nextStep,
              dueDate,
              sourceIds: [],
              expectedRevision: stored?.revision ?? work.revision,
            })
            setDraft(key, undefined)
            window.dispatchEvent(new Event('paa-record-updated'))
            onSaved()
          } catch (e) {
            setError(e as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        <ProgressFields
          value={value}
          change={(content) =>
            setDraft(key, { content, revision: stored?.revision ?? work.revision })
          }
        />
        <ErrorNotice>{error}</ErrorNotice>
        {error && (
          <ConflictRecovery<Work>
            load={() => api(`/work-items/${work.id}`)}
            render={(latest) => (
              <>
                <p>
                  {latest.title}：{latest.summary}
                </p>
                <p>{latest.blocker}</p>
                <p>{latest.nextStep}</p>
              </>
            )}
            keep={(latest) => {
              setDraft(key, { content: value, revision: latest.revision })
              setError('')
            }}
            replace={(latest) => {
              setDraft(key, { content: latest, revision: latest.revision })
              setError('')
            }}
          />
        )}
        <div className="form-actions">
          <button type="button" onClick={onClose}>
            稍后继续
          </button>
          <BusyButton busy={busy} className="primary">
            保存更正
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
export function WorkDetail({
  recordId,
  recordSearch,
}: { recordId?: string; recordSearch?: string } = {}) {
  const navigate = useNavigate()
  const [deleting, setDeleting] = useState(false)
  const location = useLocation()
  const params = useParams()
  const id = recordId ?? params.id
  const { data, error, refresh } = useResource<Work>(
    `/work-items/${id}${recordSearch ?? location.search}`,
    5000,
  )
  const { identity } = useWorkspace()
  const [editing, setEditing] = useState(false)
  return (
    <div className="page narrow">
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data && (
        <>
          <div className="page-heading">
            <div>
              <Status value={data.status} />
              {data.historical && (
                <small>
                  历史修订 · 第 {data.revision} 版{' '}
                  <Link to={`/work/${data.id}`} state={detailState(location)}>
                    查看最新工作
                  </Link>
                </small>
              )}
              <h2>{data.title}</h2>
            </div>
            {data.ownerId === identity.member.id && !data.historical && (
              <Actions label="管理工作">
                <button role="menuitem" onClick={() => setEditing(true)}>
                  编辑工作
                </button>
                <button role="menuitem" className="danger" onClick={() => setDeleting(true)}>
                  删除工作
                </button>
              </Actions>
            )}
          </div>
          <div className="panel">
            {data.dueDate && <p>截止日期：{data.dueDate}</p>}
            <p className="preserve">{data.summary}</p>
            {data.blocker && <p className="blocker">阻碍：{data.blocker}</p>}
            {data.nextStep && <p>下一步：{data.nextStep}</p>}
            <small>
              更新于 {dateLabel(data.updatedAt)} · 第 {data.revision} 版
            </small>
          </div>
          <BusinessSources
            sources={data.businessLinks ?? []}
            endpoint={`/work-items/${data.id}/business-sources`}
          />
          {deleting && (
            <DeleteRecord
              kind="work-items"
              id={data.id}
              title={data.title}
              revision={data.revision}
              onClose={() => setDeleting(false)}
              onDeleted={() => {
                const back = detailReturn(location.pathname, location.state)
                navigate(back.path, { state: back.state, replace: true })
              }}
            />
          )}
          <details className="record-evidence">
            <summary>进展记录与来源</summary>
            <div className="timeline">
              {data.history?.map((h) => (
                <article key={h.id}>
                  <small>
                    第 {h.revision} 版 · {dateLabel(h.createdAt)}
                  </small>
                  <p>{h.content.summary}</p>
                  {h.sourceIds.length ? (
                    h.sourceIds.map((source) =>
                      h.deletedSourceIds?.includes(source) ? (
                        <span className="muted" key={source}>
                          原始消息已删除
                        </span>
                      ) : (
                        <Link key={source} to={`/messages/${source}`} state={detailState(location)}>
                          查看原始上报
                        </Link>
                      ),
                    )
                  ) : (
                    <small>
                      {h.revision === 1 && data.origin === 'manual' ? '手动创建' : '手动更新'}
                    </small>
                  )}
                </article>
              ))}
            </div>
          </details>
          {editing && (
            <WorkEditor
              work={data}
              onClose={() => setEditing(false)}
              onSaved={() => {
                setEditing(false)
                refresh()
              }}
            />
          )}
        </>
      )}
    </div>
  )
}
export const reportLabels: Record<keyof ReportContent, string> = {
  completed: '完成的工作',
  ongoing: '进行中的工作',
  blockers: '问题与阻碍',
  next: '下一步计划',
}
export function ReportBody({ content }: { content: ReportContent }) {
  return (
    <div className="report-body">
      {Object.entries(reportLabels).map(([key, label]) => (
        <section key={key}>
          <h3>{label}</h3>
          <p className="preserve">{content[key as keyof ReportContent] || '暂无记录'}</p>
        </section>
      ))}
    </div>
  )
}
export function ReportsPage() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const kind = params.get('kind') === 'weekly' ? 'weekly' : 'daily'
  const todo = params.get('view') !== 'all'
  const { data, error, refresh, loadMore, loading } = usePagedResource<Report>(
    todo ? null : `/reports?kind=${kind}`,
    'period',
    2000,
  )
  const rules = useResource<Rules>('/settings/report-rules')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const [showRules, setShowRules] = useState(false)
  const { notify } = useWorkspace()
  const selectedDate = params.get('date') || todayIn(rules.data?.timezone ?? 'Asia/Shanghai')
  return (
    <div className="page records-page reports-page">
      <div className="page-heading">
        <div>
          <h2>我的报告</h2>
        </div>
        <button onClick={() => setShowRules(true)}>
          <CalendarDays size={16} />
          汇报安排
        </button>
      </div>
      <div className="records-surface">
        <div className="records-navigation">
          <div className="tabs report-view-tabs">
            <button
              aria-pressed={todo}
              className={todo ? 'active' : ''}
              onClick={() => setParams({ kind, view: 'todo' })}
            >
              汇报待办
            </button>
            <button
              aria-pressed={!todo}
              className={!todo ? 'active' : ''}
              onClick={() => setParams({ kind, view: 'all' })}
            >
              全部报告
            </button>
          </div>
          <div className="report-kind-switch" role="group" aria-label="报告类型">
            <button
              className={kind === 'daily' ? 'active' : ''}
              aria-pressed={kind === 'daily'}
              onClick={() =>
                setParams({ kind: 'daily', date: selectedDate, view: todo ? 'todo' : 'all' })
              }
            >
              日报
            </button>
            <button
              className={kind === 'weekly' ? 'active' : ''}
              aria-pressed={kind === 'weekly'}
              onClick={() =>
                setParams({ kind: 'weekly', date: selectedDate, view: todo ? 'todo' : 'all' })
              }
            >
              周报
            </button>
          </div>
        </div>
        {!todo && (
          <div className="records-toolbar report-generate">
            <label className="record-date-field">
              <span>报告日期</span>
              <input
                type="date"
                aria-label="报告日期"
                value={selectedDate}
                onClick={(event) => {
                  try {
                    event.currentTarget.showPicker?.()
                  } catch {
                    /* Native picker unavailable. */
                  }
                }}
                onChange={(e) => setParams({ kind, date: e.target.value, view: 'all' })}
              />
            </label>
            <BusyButton
              busy={busy}
              className="primary"
              onClick={async () => {
                setBusy(true)
                try {
                  await write(
                    '/reports/generate',
                    { kind, date: selectedDate },
                    'POST',
                    crypto.randomUUID(),
                  )
                  refresh()
                  notify('已准备报告，生成状态会自动更新')
                } catch (e) {
                  setFailure(e as Error)
                } finally {
                  setBusy(false)
                }
              }}
            >
              <Sparkles size={16} />
              生成{kind === 'daily' ? '日报' : '周报'}
            </BusyButton>
          </div>
        )}
        <ErrorNotice retry={refresh}>{failure || error}</ErrorNotice>
        {todo ? (
          <ReportObligations />
        ) : (
          <div className="records-results" aria-label="报告列表">
            {data?.items.length ? (
              <div className="record-list">
                {data.items.map((report) => (
                  <div className="record-row report-row" key={report.id}>
                    <Link
                      to={`/reports/${report.id}`}
                      state={detailState(location)}
                      className="record-main report-entry-link"
                    >
                      <span className="record-type-icon" aria-hidden="true">
                        <FileText size={21} />
                      </span>
                      <div className="record-main">
                        <h3>
                          {report.kind === 'weekly' ? '周报' : '日报'} ·{' '}
                          <span className="record-period">{report.period}</span>
                          {report.kind === 'weekly' && (
                            <>
                              {' '}
                              — <span className="record-period">{report.periodEnd}</span>
                            </>
                          )}
                        </h3>
                        <p>
                          <span
                            className={`status ${report.publishedRevision ? 'submitted' : 'draft'}`}
                          >
                            {report.publishedRevision
                              ? `已提交第 ${report.publishedRevision} 版${report.revision !== report.publishedRevision ? ' · 有未提交更正' : ''}`
                              : '草稿'}
                          </span>
                        </p>
                        <small>
                          {report.job?.state === 'running' || report.job?.state === 'queued'
                            ? '正在整理'
                            : ''}
                          {report.job?.error ? '生成未完成' : ''}
                        </small>
                      </div>
                      <time className="record-updated">{dateLabel(report.updatedAt)}</time>
                      <ChevronRight size={18} />
                    </Link>
                    <ReportActions report={report} onDeleted={refresh} />
                  </div>
                ))}
                {data.nextCursor && (
                  <button className="records-load-more" disabled={loading} onClick={loadMore}>
                    加载更早报告
                  </button>
                )}
              </div>
            ) : data ? (
              <RecordEmpty
                icon={<FileText size={27} />}
                title={`还没有${kind === 'daily' ? '日报' : '周报'}`}
              >
                选择上方日期生成草稿，整理后即可提交。
              </RecordEmpty>
            ) : (
              !error && (
                <p className="records-loading" role="status">
                  正在读取报告…
                </p>
              )
            )}
          </div>
        )}
      </div>
      {showRules && (
        <Modal title="我的汇报安排" onClose={() => setShowRules(false)}>
          {rules.data ? (
            <>
              <p>公司时区：{timezoneLabel(rules.data.timezone)}</p>
              {(['daily', 'weekly'] as const).map((k) => (
                <div className="panel" key={k}>
                  <h3>{k === 'daily' ? '日报' : '周报'}</h3>
                  <p>
                    {rules.data![k].enabled
                      ? `${rules.data![k].days.map((d) => ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][d]).join('、')} ${rules.data![k].generateTime} 生成，${rules.data![k].deadline} 前提交`
                      : '尚未启用自动生成，可手动准备报告'}
                  </p>
                  {rules.data!.effectivePeriods?.[k] && (
                    <p className="muted">
                      当前设置从 {rules.data!.effectivePeriods[k]} 起的周期生效
                    </p>
                  )}
                  {rules.data![k].enabled && (
                    <p className="muted">
                      {rules.data![k].reminders === false
                        ? '站内提醒已关闭'
                        : `草稿就绪、截止前 ${rules.data![k].beforeMinutes ?? 30} 分钟及逾期后提醒`}
                    </p>
                  )}
                </div>
              ))}
            </>
          ) : (
            <ErrorNotice>{rules.error || '正在读取…'}</ErrorNotice>
          )}
        </Modal>
      )}
    </div>
  )
}
export function ReportDetail({
  recordId,
  recordSearch,
  onRecordDeleted,
}: { recordId?: string; recordSearch?: string; onRecordDeleted?: () => void } = {}) {
  const navigate = useNavigate()
  const location = useLocation()
  const [deleting, setDeleting] = useState(false)
  const params = useParams()
  const id = recordId ?? params.id
  const { data, error, refresh } = useResource<Report>(
    `/reports/${id}${recordSearch ?? location.search}`,
    2000,
  )
  const { identity, drafts, setDraft, notify } = useWorkspace()
  const [editing, setEditing] = useState(new URLSearchParams(location.search).get('edit') === '1')
  const [submit, setSubmit] = useState(false)
  const [history, setHistory] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const key = `report:${id}`
  const saved = drafts[key] as { content: ReportContent; revision: number } | undefined
  const value = saved?.content ?? data?.content
  const own =
    data?.ownerId === identity.member.id && identity.member.role === 'employee' && !data.historical
  async function save() {
    if (!data || !value) return
    setBusy(true)
    try {
      await write(
        `/reports/${id}`,
        { content: value, expectedRevision: saved?.revision ?? data.revision },
        'PATCH',
      )
      setDraft(key, undefined)
      setEditing(false)
      refresh()
      notify('草稿已保存')
    } catch (e) {
      setFailure(e as Error)
    } finally {
      setBusy(false)
    }
  }
  if (data?.ownerId === identity.member.id && identity.member.role === 'admin')
    return <Navigate to="/team" replace />
  return (
    <div className="page narrow">
      <ErrorNotice retry={refresh}>{failure || error}</ErrorNotice>
      {data && (
        <>
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                {data.kind === 'daily' ? '日报' : '周报'} · {timezoneLabel(data.timezone)}
              </span>
              {data.ownerName && <p className="report-owner">{data.ownerName}</p>}
              <h2>
                {data.period}
                {data.kind === 'weekly' ? ` — ${data.periodEnd}` : ''}
              </h2>
              <p>
                {data.publishedRevision
                  ? `已提交第 ${data.historical ? data.revision : data.publishedRevision} 版`
                  : '草稿'}
              </p>
            </div>
            {(identity.member.role === 'admin' || (own && !data.publishedRevision)) && (
              <Actions label="管理报告">
                <button role="menuitem" className="danger" onClick={() => setDeleting(true)}>
                  删除报告
                </button>
              </Actions>
            )}
            {own && !editing && (
              <div className="inline">
                <button onClick={() => setEditing(!editing)}>编辑草稿</button>
                <button
                  className="primary"
                  disabled={editing || !!saved || data.revision === data.publishedRevision}
                  onClick={() => setSubmit(true)}
                >
                  提交报告
                </button>
              </div>
            )}
          </div>
          {deleting && (
            <DeleteRecord
              kind="reports"
              id={data.id}
              title={`${data.period}${data.kind === 'daily' ? '日报' : '周报'}`}
              revision={data.managementRevision ?? data.revision}
              onClose={() => setDeleting(false)}
              onDeleted={() => {
                if (onRecordDeleted) {
                  onRecordDeleted()
                  return
                }
                const back = detailReturn(location.pathname, location.state)
                navigate(back.path, { state: back.state, replace: true })
              }}
            />
          )}
          {data.job && <JobNotice job={data.job} refresh={refresh} />}
          {data.candidate && own && (
            <div className="notice">
              <span>新的生成结果已保留，现有草稿未被覆盖。</span>
              <button
                onClick={() => {
                  if (!window.confirm('采用新的生成结果将替换当前草稿，已提交版本保持不变。继续？'))
                    return
                  void write(`/reports/${id}/candidate`, { expectedRevision: data.revision })
                    .then(refresh)
                    .catch((e) => setFailure(e as Error))
                }}
              >
                采用生成结果
              </button>
            </div>
          )}
          {editing && value ? (
            <form
              className="panel report-editor"
              onSubmit={(e) => {
                e.preventDefault()
                void save()
              }}
            >
              {Object.entries(reportLabels).map(([field, label]) => (
                <label key={field}>
                  {label}
                  <AutoTextarea
                    rows={2}
                    maxLength={8000}
                    value={value[field as keyof ReportContent]}
                    onChange={(e) =>
                      setDraft(key, {
                        content: { ...value, [field]: e.target.value },
                        revision: saved?.revision ?? data.revision,
                      })
                    }
                  />
                </label>
              ))}
              {failure && (
                <ConflictRecovery<Report>
                  load={() => api(`/reports/${id}`)}
                  render={(latest) => <ReportBody content={latest.content} />}
                  keep={(latest) => {
                    setDraft(key, { content: value, revision: latest.revision })
                    setFailure('')
                  }}
                  replace={(latest) => {
                    setDraft(key, { content: latest.content, revision: latest.revision })
                    setFailure('')
                  }}
                />
              )}
              <div className="form-actions editor-actions">
                <button type="button" onClick={() => setEditing(false)}>
                  稍后继续
                </button>
                <BusyButton busy={busy} className="primary">
                  保存草稿
                </BusyButton>
              </div>
            </form>
          ) : (
            <div className="panel">
              <ReportBody content={data.content} />
            </div>
          )}
          <small>
            更新于 {dateLabel(data.updatedAt)} · 第 {data.revision} 版
          </small>
          <ReportSources report={data} />
          {data.revisions.length > 0 && (
            <section>
              <h3>提交历史</h3>
              {data.revisions.map((r, index) => (
                <button className="history-row" key={r.revision} onClick={() => setHistory(index)}>
                  第 {r.revision} 版 · {dateLabel(r.submittedAt)}
                  <ChevronRight size={16} />
                </button>
              ))}
            </section>
          )}
          {submit && (
            <Modal title="提交报告" onClose={() => setSubmit(false)}>
              <p>确认提交这份报告？</p>
              <div className="form-actions">
                <button onClick={() => setSubmit(false)}>继续检查</button>
                <BusyButton
                  busy={busy}
                  className="primary"
                  onClick={async () => {
                    setBusy(true)
                    try {
                      await write(
                        `/reports/${id}/submit`,
                        { expectedRevision: data.revision },
                        'POST',
                        crypto.randomUUID(),
                      )
                      setSubmit(false)
                      refresh()
                      notify('报告已提交')
                    } catch (e) {
                      setFailure(e as Error)
                    } finally {
                      setBusy(false)
                    }
                  }}
                >
                  确认提交
                </BusyButton>
              </div>
            </Modal>
          )}
          {history !== null && (
            <Modal
              title={`已提交 · 第 ${data.revisions[history].revision} 版`}
              onClose={() => setHistory(null)}
            >
              <ReportBody content={data.revisions[history].content} />
            </Modal>
          )}
        </>
      )}
    </div>
  )
}
function ReportSources({ report }: { report: Report }) {
  const location = useLocation()
  const { data, error, refresh } = useResource<{
    items: {
      id: string
      workId: string
      title: string
      sourceIds: string[]
      deletedSourceIds?: string[]
      workDeleted?: boolean
      revision: number
    }[]
  }>(`/reports/${report.id}/sources?revision=${report.revision}`)
  if (error) return <ErrorNotice retry={refresh}>{error}</ErrorNotice>
  return data?.items.length ? (
    <details className="record-evidence">
      <summary>工作依据</summary>
      {data.items.map((item) => (
        <div className="source-row" key={item.id}>
          {item.workDeleted ? (
            <span>{item.title} · 工作已删除</span>
          ) : (
            <Link
              to={`/work/${item.workId}?revision=${item.revision}`}
              state={detailState(location)}
            >
              {item.title} · 第 {item.revision} 版
            </Link>
          )}
          {item.sourceIds.map((id) =>
            item.deletedSourceIds?.includes(id) ? (
              <span key={id} className="muted">
                原始消息已删除
              </span>
            ) : (
              <Link key={id} to={`/messages/${id}`} state={detailState(location)}>
                原始上报
              </Link>
            ),
          )}
        </div>
      ))}
    </details>
  ) : null
}
