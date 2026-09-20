import type { Report, ReportContent } from '@paa/api-contracts'
import { reportNeedsPolling } from '@web/api/job-feedback'
import { Actions } from '@web/components/Actions'
import { AutoTextarea } from '@web/components/AutoTextarea'
import { BusyButton } from '@web/components/BusyButton'
import { ConflictRecovery } from '@web/components/ConflictRecovery'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { JobNotice } from '@web/features/jobs/components/JobNotice'
import { DeleteRecord } from '@web/features/records/components/DeleteRecord'
import {
  generateReportCandidate,
  readReport,
  reportDetailPath,
  submitReport,
  updateReport,
} from '@web/features/reports/api/requests'
import { ReportBody, reportLabels } from '@web/features/reports/components/ReportBody'
import { ReportSources } from '@web/features/reports/components/ReportSources'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { dateLabel } from '@web/utils/date'
import { detailReturn } from '@web/utils/navigation'
import { timezoneLabel } from '@web/utils/timezones'
import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

export function ReportDetail({
  recordId,
  recordSearch,
  onRecordDeleted,
}: { recordId?: string; recordSearch?: string; onRecordDeleted?: () => void } = {}) {
  const navigate = useNavigate()
  const location = useLocation()
  const [deleting, setDeleting] = useState(false)
  const id = recordId
  const { data, error, refresh } = useResource<Report>(
    reportDetailPath(id, recordSearch ?? location.search),
    2000,
    reportNeedsPolling,
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
      await updateReport(id, { content: value, expectedRevision: saved?.revision ?? data.revision })
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
                  void generateReportCandidate(id, { expectedRevision: data.revision })
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
                  load={() => readReport(id)}
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
                      await submitReport(
                        id,
                        { expectedRevision: data.revision },
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
