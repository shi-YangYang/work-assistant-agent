import styles from './ChatHistory.module.css'
import type { BusinessAction, Identity, Page, WorkMessage } from '@paa/api-contracts'
import { Empty } from '@web/components/Empty'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { BusinessActionCard } from '@web/features/assistant/components/BusinessActionCard'
import { MessageCard } from '@web/features/assistant/components/MessageCard'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { exampleText } from '@web/features/assistant/utils/session'
import type * as React from 'react'

export function ChatHistory({
  scroller,
  atBottomRef,
  setNewReply,
  refresh,
  error,
  nextCursor,
  loading,
  loadMore,
  messages,
  conversationId,
  data,
  identity,
  locked,
  composer,
  notify,
  change,
  textInput,
  actionReceipts,
}: {
  scroller: React.RefObject<HTMLDivElement | null>
  atBottomRef: React.RefObject<boolean>
  setNewReply: React.Dispatch<React.SetStateAction<boolean>>
  refresh: () => Promise<void>
  error: string | Error
  nextCursor: string | null | undefined
  loading: boolean
  loadMore: () => Promise<void>
  messages: WorkMessage[]
  conversationId: string | undefined
  data: Page<WorkMessage> | null
  identity: Identity
  locked: boolean
  composer: Composer
  notify: (value: string) => void
  change: (next: Composer) => void
  textInput: React.RefObject<HTMLTextAreaElement | null>
  actionReceipts: {
    data: { items: BusinessAction[] } | null
    error: string | Error
    refresh: () => void
  }
}) {
  return (
    <div
      className={styles['chat-scroll']}
      ref={scroller}
      onScroll={() => {
        const node = scroller.current
        if (node) {
          atBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80
          if (atBottomRef.current) setNewReply(false)
        }
      }}
    >
      <div className={styles['chat-content']} data-chat-content>
        <ErrorNotice retry={refresh}>{error}</ErrorNotice>
        {nextCursor && (
          <button className={styles['load-more']} disabled={loading} onClick={loadMore}>
            加载更早消息
          </button>
        )}
        {!messages.length && !error && (!conversationId || !!data) && (
          <Empty title={identity.member.role === 'admin' ? '从团队进展开始' : '从今天的工作开始'}>
            <span className={styles['assistant-examples']}>
              {(identity.member.role === 'admin'
                ? ['团队当前有哪些阻碍？', '本周员工有哪些工作进展？', '查看最近提交的周报']
                : ['帮我创建工作：', '生成今天的日报', '查看我还没交的报告']
              ).map((text) => (
                <button
                  key={text}
                  disabled={locked}
                  onClick={() => {
                    const next = exampleText(composer.text, text)
                    if (next === composer.text)
                      notify('输入框已有内容，请继续编辑；示例没有覆盖它。')
                    else change({ ...composer, text: next, key: '' })
                    textInput.current?.focus()
                  }}
                >
                  {text}
                </button>
              ))}
            </span>
          </Empty>
        )}
        {actionReceipts.data?.items
          .filter((action) => !messages.some((message) => message.id === action.messageId))
          .map((action) => (
            <BusinessActionCard key={action.id} action={action} refresh={actionReceipts.refresh} />
          ))}
        {messages.map((message) => (
          <MessageCard
            key={message.id}
            message={message}
            own
            onChange={refresh}
            onReply={
              locked
                ? undefined
                : () => {
                    change({ ...composer, replyTo: message.id, key: '' })
                    textInput.current?.focus()
                  }
            }
          />
        ))}
      </div>
    </div>
  )
}
