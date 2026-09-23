import layoutStyles from '../styles/layout.module.css'
import utilitiesStyles from '../styles/utilities.module.css'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import type { ReactNode } from 'react'
import { useState } from 'react'

export function ConflictRecovery<T>({
  load,
  render,
  keep,
  replace,
}: {
  load: () => Promise<T>
  render: (latest: T) => ReactNode
  keep: (latest: T) => void
  replace: (latest: T) => void
}) {
  const [latest, setLatest] = useState<T | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  return (
    <section>
      <BusyButton
        type="button"
        busy={busy}
        onClick={async () => {
          setBusy(true)
          try {
            setLatest(await load())
            setError('')
          } catch (e) {
            setError(e as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        读取最新版本
      </BusyButton>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {latest && (
        <div className={layoutStyles['panel']}>
          <h3>服务端最新内容</h3>
          {render(latest)}
          <p className={utilitiesStyles['muted']}>
            核对后选择如何继续。保留当前输入时，之后保存会替换这里显示的内容；已有提交历史仍保留。
          </p>
          <div className={layoutStyles['card-actions']}>
            <button
              type="button"
              onClick={() => {
                keep(latest)
                setLatest(null)
              }}
            >
              保留当前输入，继续编辑
            </button>
            <button
              type="button"
              onClick={() => {
                replace(latest)
                setLatest(null)
              }}
            >
              使用最新内容
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
