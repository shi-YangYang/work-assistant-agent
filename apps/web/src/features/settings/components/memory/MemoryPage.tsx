import { useState } from 'react'
import { ApiError, isCancelled } from '@web/api/client'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { ActionNotice } from '@web/components/feedback/ActionNotice'
import { useQueryResource } from '@web/hooks/useQueryResource'
import { useWorkspace } from '@web/lib/workspace'
import { memoryResource, saveMemorySettings } from '../../api/memory'
import { MemoryEditor } from './MemoryEditor'
import layoutStyles from '@web/styles/layout.module.css'
import styles from './MemoryPage.module.css'

export function MemoryPage() {
  const { identity } = useWorkspace()
  return <AccountMemory key={`${identity.company.id}:${identity.member.id}`} />
}

function AccountMemory() {
  const resource = memoryResource()
  const { data, error, loading, refresh } = useQueryResource(resource)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const toggle = async () => {
    if (!data || busy) return
    setBusy(true)
    setFailure('')
    try {
      resource.set(await saveMemorySettings(!data.enabled, data.revision))
    } catch (error) {
      if (!isCancelled(error)) setFailure(error as Error)
      if (error instanceof ApiError && error.status === 409) await resource.refresh()
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className={layoutStyles['settings-page']}>
      <PageHeader title="记忆" />
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      <ActionNotice>{failure}</ActionNotice>
      {!data && loading && <p role="status">正在读取记忆…</p>}
      {data && (
        <div className={styles.content}>
          <section className={styles.setting}>
            <div>
              <h2 id="memory-toggle-label">启用跨会话记忆</h2>
              <p id="memory-toggle-description">
                让 Noria 在不同对话中记住你的偏好和背景。关闭后停止使用和自动更新，已保存内容保留。
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={data.enabled}
              aria-labelledby="memory-toggle-label"
              aria-describedby="memory-toggle-description"
              className={styles.switch}
              disabled={busy}
              aria-busy={busy}
              onClick={() => void toggle()}
            >
              <span aria-hidden="true" className={styles.track}>
                <span />
              </span>
              <span>{data.enabled ? '已开启' : '已关闭'}</span>
            </button>
          </section>
          <MemoryEditor data={data} resource={resource} settingsBusy={busy} />
        </div>
      )}
    </div>
  )
}
