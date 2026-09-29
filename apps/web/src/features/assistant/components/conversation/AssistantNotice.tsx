import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { ErrorNoticeOutlet } from '@web/components/feedback/ErrorNoticeScope'
import styles from './Conversations.module.css'

export type AssistantNoticeData = { error: Error | string; retry?: () => void }

export function AssistantNotice({
  notice,
  pending = false,
}: {
  notice?: AssistantNoticeData
  pending?: boolean
}) {
  const pendingHint =
    '原消息的提交结果尚未确认。请原样重试以确认结果，不会重复创建消息；确认前暂不修改内容。'
  return (
    <>
      <ErrorNotice
        priority={10}
        retry={notice?.retry}
        hint={pending && notice?.error ? pendingHint : undefined}
      >
        {notice?.error || (pending ? pendingHint : '')}
      </ErrorNotice>
      <ErrorNoticeOutlet label="工作助手提示" className={styles['assistant-notice']} />
    </>
  )
}
