import type { Conversation, Page } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import {
  readConversation,
  readConversationDeletion,
  readMoreConversations,
} from '@web/features/assistant/api/requests'
import { List, MessageSquare, Pencil, Search, Trash2, X } from 'lucide-react'
import type * as React from 'react'
import { Link } from 'react-router'

export function ConversationPicker({
  picker,
  setExpanded,
  closePicker,
  pickerButton,
  expanded,
  search,
  setSearch,
  setOlder,
  setCursor,
  list,
  items,
  conversationId,
  stopBeforeAction,
  setEditing,
  setImpact,
  setDeleting,
  setFailure,
  nextCursor,
}: {
  picker: React.RefObject<HTMLDivElement | null>
  setExpanded: (open: boolean) => void
  closePicker: () => void
  pickerButton: React.RefObject<HTMLButtonElement | null>
  expanded: boolean
  search: string
  setSearch: React.Dispatch<React.SetStateAction<string>>
  setOlder: React.Dispatch<React.SetStateAction<Conversation[]>>
  setCursor: React.Dispatch<React.SetStateAction<string | null | undefined>>
  list: { data: Page<Conversation> | null; error: string | Error; refresh: () => void }
  items: Conversation[]
  conversationId: string | undefined
  stopBeforeAction: () => boolean
  setEditing: React.Dispatch<React.SetStateAction<Conversation | null>>
  setImpact: React.Dispatch<React.SetStateAction<{ retainedSources: number } | null>>
  setDeleting: React.Dispatch<React.SetStateAction<Conversation | null>>
  setFailure: React.Dispatch<React.SetStateAction<string | Error>>
  nextCursor: string | null | undefined
}) {
  return (
    <div
      ref={picker}
      className="conversation-picker"
      onBlur={(event) => {
        if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node))
          setExpanded(false)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          closePicker()
        }
      }}
    >
      <button
        ref={pickerButton}
        className="icon-button"
        aria-label="会话列表"
        aria-haspopup="dialog"
        aria-expanded={expanded}
        aria-controls="conversation-picker"
        aria-describedby={expanded ? undefined : 'conversation-picker-tip'}
        onClick={() => setExpanded(!expanded)}
      >
        <List size={20} />
      </button>
      {!expanded && (
        <span className="conversation-tooltip" role="tooltip" id="conversation-picker-tip">
          会话列表
        </span>
      )}
      {expanded && (
        <div
          className="conversation-popover"
          id="conversation-picker"
          role="dialog"
          aria-label="会话列表"
        >
          <div className="conversation-popover-heading">
            <h2>会话</h2>
            <button className="icon-button" aria-label="收起会话列表" onClick={closePicker}>
              <X size={18} />
            </button>
          </div>
          <label className="conversation-search">
            <Search size={15} />
            <input
              autoFocus
              aria-label="搜索会话"
              placeholder="搜索会话"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setOlder([])
                setCursor(undefined)
              }}
            />
          </label>
          <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
          <div className="conversation-list">
            {items.map((item) => (
              <div
                key={item.id}
                className={`conversation-row ${item.id === conversationId ? 'active' : ''}`}
              >
                <Link to={`/assistant/${item.id}`} title={item.title} onClick={closePicker}>
                  <MessageSquare size={16} />
                  <span>{item.title}</span>
                </Link>
                <div className="conversation-row-actions">
                  <button
                    className="icon-button"
                    aria-label={`重命名会话：${item.title}`}
                    title="重命名"
                    onClick={() => {
                      if (stopBeforeAction()) {
                        closePicker()
                        setEditing(item)
                      }
                    }}
                  >
                    <Pencil size={15} />
                  </button>
                  <button
                    className="icon-button danger"
                    aria-label={`删除会话：${item.title}`}
                    title="删除会话"
                    onClick={async () => {
                      if (!stopBeforeAction()) return
                      closePicker()
                      try {
                        const latest = await readConversation(item)
                        const value = await readConversationDeletion(item)
                        setImpact(value)
                        setDeleting(latest)
                      } catch (e) {
                        setFailure(e as Error)
                      }
                    }}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
          {nextCursor && (
            <button
              onClick={async () => {
                try {
                  const next = await readMoreConversations(search, nextCursor)
                  setOlder((previous) => [...previous, ...next.items])
                  setCursor(next.nextCursor)
                } catch (e) {
                  setFailure(e as Error)
                }
              }}
            >
              加载更多
            </button>
          )}
          {!items.length && list.data && (
            <p className="muted">{search ? '没有匹配的会话' : '还没有会话'}</p>
          )}
        </div>
      )}
    </div>
  )
}
