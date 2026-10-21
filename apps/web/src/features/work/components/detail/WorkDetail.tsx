import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import layoutStyles from '../../../../styles/layout.module.css'
import controlsStyles from '../../../../styles/controls.module.css'
import utilitiesStyles from '../../../../styles/utilities.module.css'
import recordDetailStyles from '../../../../styles/patterns/RecordDetail.module.css'
import styles from './WorkDetail.module.css'
import { WorkContent } from '../content/WorkContent'
import { WorkMaterials } from '../materials/WorkMaterials'
import type { Work } from '@paa/api-contracts'
import { DetailBackLink } from '@web/components/navigation/DetailBackLink'
import { Actions } from '@web/components/actions/Actions'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Status } from '@web/components/feedback/Status'
import { Modal } from '@web/components/overlays/Modal'
import { DeleteRecord } from '@web/features/records/components/DeleteRecord'
import { workSourcesPath } from '@web/features/sources/api/requests'
import { BusinessSources } from '@web/features/sources/components/BusinessSources'
import { workDetailPath } from '@web/features/work/api/requests'
import { WorkHistory } from './WorkHistory'
import { WorkEditor } from '@web/features/work/components/editor/WorkEditor'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { detailReturn } from '@web/utils/navigation'
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
  )
  const { identity } = useWorkspace()
  const [editing, setEditing] = useState(false)
  const [materialsOpen, setMaterialsOpen] = useState(false)
  const own = data?.ownerId === identity.member.id && !data?.historical
  const previous = detailReturn(location.pathname + location.search, location.state)
  const latestPath = `/work/${data?.id ?? id}`
  const back =
    previous.path === '/work' || previous.path === location.pathname + location.search
      ? { path: latestPath, state: null }
      : previous
  return (
    <div
      className={`${layoutStyles['page']} ${styles['work-page']} ${recordDetailStyles['detail']}`}
      data-compact={compact}
      data-scroll-container
    >
      {!compact && !data?.historical && <DetailBackLink />}
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data && (
        <>
          {data.historical && (
            <>
              <DetailBackLink
                destination={back}
                label={back.path === latestPath ? '返回最新版本' : '返回上一步'}
                replace
                embedded={compact}
              />
              <div className={styles.version}>
                <span>历史版本 · 第 {data.revision} 版</span>
                {back.path !== latestPath && (
                  <Link to={latestPath} replace>
                    查看最新版本
                  </Link>
                )}
              </div>
            </>
          )}
          <PageHeader
            title={data.title}
            context={compact ? 'embedded' : 'detail'}
            description={
              <div className={styles.metadata}>
                <Status value={data.status} />
                {data.dueDate && <span>截止 {data.dueDate}</span>}
              </div>
            }
            actions={
              (own || !!data.materialIds?.length) && (
                <div className={styles.actions}>
                  {!!data.materialIds?.length && (
                    <button onClick={() => setMaterialsOpen(true)}>
                      全部附件 · {data.materialIds.length}
                    </button>
                  )}
                  {own && (
                    <button
                      onClick={() => navigate(`/assistant?workId=${encodeURIComponent(data.id)}`)}
                    >
                      让助手协助
                    </button>
                  )}
                  {own && (
                    <Actions label="管理工作">
                      <button role="menuitem" onClick={() => setEditing(true)}>
                        编辑工作属性
                      </button>
                      <button
                        role="menuitem"
                        className={controlsStyles['danger']}
                        onClick={() => setDeleting(true)}
                      >
                        删除工作
                      </button>
                    </Actions>
                  )}
                </div>
              )
            }
          />
          <WorkContent
            key={`content:${identity.company.id}:${identity.member.id}:${data.id}:${!!data.historical}`}
            work={data}
            own={data.ownerId === identity.member.id && !data.historical}
            saved={refresh}
          />
          {(data.blocker || data.nextStep) && (
            <div className={styles.supplement}>
              {data.blocker && (
                <p className={utilitiesStyles['error-text']}>阻碍：{data.blocker}</p>
              )}
              {data.nextStep && <p>下一步：{data.nextStep}</p>}
            </div>
          )}
          <section className={styles.history} aria-label="修改记录">
            <h3>修改记录</h3>
            <WorkHistory key={`${data.id}:${data.revision}:${!!data.historical}`} work={data} />
            <BusinessSources
              sources={data.businessLinks ?? []}
              endpoint={workSourcesPath(data.id)}
            />
          </section>
          {deleting && data.ownerId === identity.member.id && !data.historical && (
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
          {materialsOpen && (
            <Modal title="全部附件" onClose={() => setMaterialsOpen(false)}>
              <WorkMaterials work={data} own={own} saved={refresh} />
            </Modal>
          )}
          {editing && data.ownerId === identity.member.id && !data.historical && (
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
