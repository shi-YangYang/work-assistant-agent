import styles from './ChatHistory.module.css'
import type { BusinessAction, Identity, Page, WorkMessage } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { BusinessActionCard } from '@web/features/assistant/components/BusinessActionCard'
import { MessageCard } from '@web/features/assistant/components/MessageCard'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import type * as React from 'react'
import { Sparkles } from 'lucide-react'

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
  locked,
  composer,
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
      data-empty={!messages.length && !error && (!conversationId || !!data)}
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
          <div className={styles['assistant-welcome']}>
            <div className={styles['welcome-orbit']} aria-hidden="true">
              <span />
              <span />
              <div>
                <Sparkles size={30} />
              </div>
            </div>
            <span className={styles['welcome-eyebrow']}>
              <span />
              你的工作伙伴
            </span>
            <h2>今天，想推进什么？</h2>
            <p>从一个想法、一份材料，或手头的工作开始。</p>
          </div>
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
