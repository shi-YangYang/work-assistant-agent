import type { Work } from '@paa/api-contracts'
import { Actions } from '@web/components/Actions'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Status } from '@web/components/Status'
import { DeleteRecord } from '@web/features/records/components/DeleteRecord'
import { workSourcesPath } from '@web/features/sources/api/requests'
import { BusinessSources } from '@web/features/sources/components/BusinessSources'
import { workDetailPath } from '@web/features/work/api/requests'
import { WorkEditor } from '@web/features/work/components/WorkEditor'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { dateLabel } from '@web/utils/date'
import { detailReturn, detailState } from '@web/utils/navigation'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

export function WorkDetail({
  recordId,
  recordSearch,
}: { recordId?: string; recordSearch?: string } = {}) {
  const navigate = useNavigate()
  const [deleting, setDeleting] = useState(false)
  const location = useLocation()
  const id = recordId
  const { data, error, refresh } = useResource<Work>(
    workDetailPath(id, recordSearch ?? location.search),
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
          <BusinessSources sources={data.businessLinks ?? []} endpoint={workSourcesPath(data.id)} />
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
