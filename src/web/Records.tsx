import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ChevronRight, RefreshCw, FileText } from 'lucide-react'
import type {
  Page,
  Progress,
  Report,
  ReportContent,
  Rules,
  Work,
} from '../shared/company-contracts'
import { api, dateLabel, todayIn, useResource, write } from './api'
import { useWorkspace } from './workspace'
import { ConflictRecovery, Actions, BusyButton, Empty, ErrorNotice, Modal, Status } from './ui'
import { JobNotice, ProgressFields } from './Assistant'

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
  return (
    <div className="record-list">
      {items.map((work) => (
        <div className="record-row" key={work.id}>
          <Link className="record-main" to={`/work/${work.id}`}>
            <div className="row-between">
              <h3>{work.title}</h3>
              <Status value={work.status} />
            </div>
            <p>{work.summary}</p>
            <small>
              {work.blocker
                ? `阻碍：${work.blocker}`
                : work.nextStep
                  ? `下一步：${work.nextStep}`
                  : '暂无补充'}{' '}
              · {dateLabel(work.updatedAt)}
            </small>
          </Link>
          {own ? (
            <Actions>
              <button role="menuitem" onClick={() => setEditing(work)}>
                更正工作进展
              </button>
            </Actions>
          ) : (
            <ChevronRight size={18} />
          )}
        </div>
      ))}
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
  const { data, error, refresh } = useResource<Page<Work>>('/work-items')
  const [search, setSearch] = useSearchParams()
  const query = search.get('q') ?? ''
  const status = search.get('status') ?? ''
  const items =
    data?.items.filter(
      (w) => `${w.title} ${w.summary}`.includes(query) && (!status || w.status === status),
    ) ?? []
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>我的工作</h2>
          <p>只记录你已经确认的进展。</p>
        </div>
        <button aria-label="刷新工作" onClick={refresh}>
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="filters">
        <input
          aria-label="搜索工作"
          placeholder="搜索工作事项"
          value={query}
          onChange={(e) => setSearch({ q: e.target.value, status }, { replace: true })}
        />
        <select
          aria-label="工作状态"
          value={status}
          onChange={(e) => setSearch({ q: query, status: e.target.value }, { replace: true })}
        >
          <option value="">全部状态</option>
          <option value="in_progress">进行中</option>
          <option value="blocked">有阻碍</option>
          <option value="done">已完成</option>
        </select>
      </div>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {items.length ? (
        <WorkList items={items} own refresh={refresh} />
      ) : (
        <Empty title={query || status ? '没有符合条件的工作' : '还没有已确认的工作'}>
          在工作助手中发送进展，并确认助手整理的建议。
        </Empty>
      )}
    </div>
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
  const [error, setError] = useState('')
  return (
    <Modal title="更正工作进展" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          try {
            const { title, summary, status, blocker, nextStep } = value
            await write(`/work-items/${work.id}/progress`, {
              title,
              summary,
              status,
              blocker,
              nextStep,
              sourceIds: [],
              expectedRevision: stored?.revision ?? work.revision,
            })
            setDraft(key, undefined)
            onSaved()
          } catch (e) {
            setError((e as Error).message)
          } finally {
            setBusy(false)
          }
        }}
      >
        <p className="muted">保存后更新看板，同时保留之前的修订记录。</p>
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
export function WorkDetail() {
  const { id } = useParams()
  const { data, error, refresh } = useResource<Work>(`/work-items/${id}`)
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
              <h2>{data.title}</h2>
            </div>
            {data.ownerId === identity.member.id && (
              <button onClick={() => setEditing(true)}>更正进展</button>
            )}
          </div>
          <div className="panel">
            <p className="preserve">{data.summary}</p>
            {data.blocker && <p className="blocker">阻碍：{data.blocker}</p>}
            {data.nextStep && <p>下一步：{data.nextStep}</p>}
            <small>
              更新于 {dateLabel(data.updatedAt)} · 第 {data.revision} 版
            </small>
          </div>
          <h3>进展记录与来源</h3>
          <div className="timeline">
            {data.history?.map((h) => (
              <article key={h.id}>
                <small>
                  第 {h.revision} 版 · {dateLabel(h.createdAt)}
                </small>
                <p>{h.content.summary}</p>
                {h.sourceIds.length ? (
                  h.sourceIds.map((source) => (
                    <Link key={source} to={`/messages/${source}`}>
                      查看原始上报
                    </Link>
                  ))
                ) : (
                  <small>员工手动更正</small>
                )}
              </article>
            ))}
          </div>
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
  const [params, setParams] = useSearchParams()
  const kind = params.get('kind') === 'weekly' ? 'weekly' : 'daily'
  const { data, error, refresh } = useResource<Page<Report>>(`/reports?kind=${kind}`, 2000)
  const rules = useResource<Rules>('/settings/report-rules')
  const [older, setOlder] = useState<{ kind: string; items: Report[]; cursor?: string | null }>({
    kind,
    items: [],
  })
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const [showRules, setShowRules] = useState(false)
  const { notify } = useWorkspace()
  const selectedDate = params.get('date') || todayIn(rules.data?.timezone ?? 'Asia/Shanghai')
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>我的报告</h2>
          <p>从确认的进展整理，审阅后再提交。</p>
        </div>
        <button onClick={() => setShowRules(true)}>汇报安排</button>
      </div>
      <div className="toolbar">
        <div className="tabs">
          <button
            className={kind === 'daily' ? 'active' : ''}
            onClick={() => setParams({ kind: 'daily', date: selectedDate })}
          >
            日报
          </button>
          <button
            className={kind === 'weekly' ? 'active' : ''}
            onClick={() => setParams({ kind: 'weekly', date: selectedDate })}
          >
            周报
          </button>
        </div>
        <div className="inline">
          <input
            type="date"
            aria-label="报告日期"
            value={selectedDate}
            onChange={(e) => setParams({ kind, date: e.target.value })}
          />
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
                setFailure((e as Error).message)
              } finally {
                setBusy(false)
              }
            }}
          >
            生成{kind === 'daily' ? '日报' : '周报'}
          </BusyButton>
        </div>
      </div>
      <ErrorNotice retry={refresh}>{failure || error}</ErrorNotice>
      {data?.items.length ? (
        <div className="record-list">
          {[...data.items, ...(older.kind === kind ? older.items : [])]
            .filter((r, i, all) => all.findIndex((x) => x.id === r.id) === i)
            .map((report) => (
              <Link to={`/reports/${report.id}`} className="record-row" key={report.id}>
                <FileText size={21} />
                <div className="record-main">
                  <h3>
                    {report.period}
                    {report.kind === 'weekly' ? ` — ${report.periodEnd}` : ''}
                  </h3>
                  <p>
                    {report.publishedRevision
                      ? `已提交第 ${report.publishedRevision} 版${report.revision !== report.publishedRevision ? ' · 有未提交更正' : ''}`
                      : '草稿，仅自己可见'}
                  </p>
                  <small>
                    {dateLabel(report.updatedAt)}
                    {report.job?.state === 'running' || report.job?.state === 'queued'
                      ? ' · 正在整理'
                      : ''}
                    {report.job?.error ? ' · 生成未完成' : ''}
                  </small>
                </div>
                <ChevronRight size={18} />
              </Link>
            ))}
          {(older.kind === kind && older.cursor !== undefined ? older.cursor : data.nextCursor) && (
            <button
              onClick={async () => {
                const next = await api<Page<Report>>(
                  `/reports?kind=${kind}&cursor=${older.kind === kind && older.cursor !== undefined ? older.cursor : data.nextCursor}`,
                )
                setOlder({
                  kind,
                  items: [...(older.kind === kind ? older.items : []), ...next.items],
                  cursor: next.nextCursor,
                })
                notify('已加载更早报告')
              }}
            >
              加载更早报告
            </button>
          )}
        </div>
      ) : (
        <Empty title="还没有报告">选择日期生成草稿，也可以在空草稿中手动填写工作。</Empty>
      )}
      {showRules && (
        <Modal title="我的汇报安排" onClose={() => setShowRules(false)}>
          {rules.data ? (
            <>
              <p>公司时区：{rules.data.timezone}</p>
              {(['daily', 'weekly'] as const).map((k) => (
                <div className="panel" key={k}>
                  <h3>{k === 'daily' ? '日报' : '周报'}</h3>
                  <p>
                    {rules.data![k].enabled
                      ? `${rules.data![k].days.map((d) => ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][d]).join('、')} ${rules.data![k].generateTime} 生成，${rules.data![k].deadline} 前提交`
                      : '尚未启用自动生成，可手动准备报告'}
                  </p>
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
export function ReportDetail() {
  const { id } = useParams()
  const { data, error, refresh } = useResource<Report>(`/reports/${id}`, 2000)
  const { identity, drafts, setDraft, notify } = useWorkspace()
  const [editing, setEditing] = useState(false)
  const [submit, setSubmit] = useState(false)
  const [history, setHistory] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const key = `report:${id}`
  const saved = drafts[key] as { content: ReportContent; revision: number } | undefined
  const value = saved?.content ?? data?.content
  const own = data?.ownerId === identity.member.id
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
      setFailure((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="page narrow">
      <ErrorNotice retry={refresh}>{failure || error}</ErrorNotice>
      {data && (
        <>
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                {data.kind === 'daily' ? '日报' : '周报'} · {data.timezone}
              </span>
              <h2>
                {data.period}
                {data.kind === 'weekly' ? ` — ${data.periodEnd}` : ''}
              </h2>
              <p>
                {data.publishedRevision
                  ? `已提交第 ${data.publishedRevision} 版`
                  : '草稿仅自己可见'}
              </p>
            </div>
            {own && (
              <div className="inline">
                <button onClick={() => setEditing(!editing)}>
                  {editing ? '稍后继续' : '编辑草稿'}
                </button>
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
                    .catch((e) => setFailure(e.message))
                }}
              >
                采用生成结果
              </button>
            </div>
          )}
          {editing && value ? (
            <form
              className="panel"
              onSubmit={(e) => {
                e.preventDefault()
                void save()
              }}
            >
              {Object.entries(reportLabels).map(([field, label]) => (
                <label key={field}>
                  {label}
                  <textarea
                    rows={4}
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
              <BusyButton busy={busy} className="primary">
                保存草稿
              </BusyButton>
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
              <p>提交后，老板／管理员可以查看这份报告。后续更正会保留为新版本。</p>
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
                      setFailure((e as Error).message)
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
  const { data, error, refresh } = useResource<{
    items: { id: string; workId: string; title: string; sourceIds: string[]; revision: number }[]
  }>(`/reports/${report.id}/sources?revision=${report.revision}`)
  if (error) return <ErrorNotice retry={refresh}>{error}</ErrorNotice>
  return data?.items.length ? (
    <section>
      <h3>工作依据</h3>
      {data.items.map((item) => (
        <div className="source-row" key={item.id}>
          <Link to={`/work/${item.workId}`}>
            {item.title} · 第 {item.revision} 版
          </Link>
          {item.sourceIds.map((id) => (
            <Link key={id} to={`/messages/${id}`}>
              原始上报
            </Link>
          ))}
        </div>
      ))}
    </section>
  ) : null
}
