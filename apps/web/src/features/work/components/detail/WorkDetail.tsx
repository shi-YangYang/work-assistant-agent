import layoutStyles from '../../../../styles/layout.module.css'
import controlsStyles from '../../../../styles/controls.module.css'
import utilitiesStyles from '../../../../styles/utilities.module.css'
import recordDetailStyles from '../../../../styles/patterns/RecordDetail.module.css'
import styles from './WorkDetail.module.css'
import type { Work } from '@paa/api-contracts'
import { Actions } from '@web/components/actions/Actions'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Status } from '@web/components/feedback/Status'
import { DeleteRecord } from '@web/features/records/components/DeleteRecord'
import { workSourcesPath } from '@web/features/sources/api/requests'
import { BusinessSources } from '@web/features/sources/components/BusinessSources'
import { workDetailPath } from '@web/features/work/api/requests'
import { WorkHistory } from './WorkHistory'
import { WorkEditor } from '@web/features/work/components/editor/WorkEditor'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { dateLabel } from '@web/utils/date'
import { detailReturn, detailState } from '@web/utils/navigation'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

export function WorkDetail({
  compact = false,
  recordId,
  recordSearch,
}: { compact?: boolean; recordId?: string; recordSearch?: string } = {}) {
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
    <div
      className={`${layoutStyles['page']} ${layoutStyles['narrow']} ${recordDetailStyles['detail']}`}
      data-compact={compact}
      data-scroll-container
    >
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data && (
        <>
          <div className={`${layoutStyles['page-heading']} ${recordDetailStyles['heading']}`}>
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
              <div className={layoutStyles['inline']}>
                <button
                  onClick={() => navigate(`/assistant?workId=${encodeURIComponent(data.id)}`)}
                >
                  让助手协助
                </button>
                <button onClick={() => setEditing(true)}>编辑工作</button>
                <Actions label="管理工作">
                  <button
                    role="menuitem"
                    className={controlsStyles['danger']}
                    onClick={() => setDeleting(true)}
                  >
                    删除工作
                  </button>
                </Actions>
              </div>
            )}
          </div>
          <div className={`${layoutStyles['panel']} ${recordDetailStyles['panel']}`}>
            {data.dueDate && <p>截止日期：{data.dueDate}</p>}
            {data.summary && <p className={utilitiesStyles['preserve']}>{data.summary}</p>}
            {!data.summary && !data.blocker && !data.nextStep && (
              <div className={styles['empty-content']}>
                <p>这项工作还没有填写具体内容</p>
                {data.ownerId === identity.member.id && !data.historical && (
                  <button onClick={() => setEditing(true)}>补充工作内容</button>
                )}
              </div>
            )}
            {data.blocker && <p className={utilitiesStyles['error-text']}>阻碍：{data.blocker}</p>}
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
          <details className={recordDetailStyles['record-evidence']}>
            <summary>进展记录与来源</summary>
            <WorkHistory work={data} />
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
