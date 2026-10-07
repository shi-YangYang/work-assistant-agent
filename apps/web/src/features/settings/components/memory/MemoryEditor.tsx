import { useState } from 'react'
import type { AssistantMemory } from '@paa/api-contracts'
import { ApiError, isCancelled } from '@web/api/client'
import { BusyButton } from '@web/components/actions/BusyButton'
import { Markdown } from '@web/components/content/Markdown'
import { MarkdownEditor } from '@web/components/forms/markdown-editor/MarkdownEditor'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import type { QueryResource } from '@web/lib/query-resource'
import { useWorkspace } from '@web/lib/workspace'
import { clearMemoryDocument, readMemory, saveMemoryDocument } from '../../api/memory'
import controls from '@web/styles/controls.module.css'
import styles from './MemoryEditor.module.css'

type Draft = { markdown: string; revision: number; baseline: string }
export function MemoryEditor({
  data,
  resource,
  settingsBusy,
}: {
  data: AssistantMemory
  resource: QueryResource<AssistantMemory>
  settingsBusy: boolean
}) {
  const { drafts, setDraft } = useWorkspace()
  const draft = drafts.memory as Draft | undefined
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [latest, setLatest] = useState<AssistantMemory | null>(null)
  const [conflict, setConflict] = useState(false)
  const length = Array.from(draft?.markdown ?? '').length
  // A switch changes the shared revision but not the document. It is safe to
  // advance that base only while the saved text still equals our original base.
  const expected = draft && data.markdown === draft.baseline ? data.revision : draft?.revision
  const cancel = () => {
    setDraft('memory', undefined)
    setConflict(false)
    setLatest(null)
    setError('')
  }
  const failure = (value: unknown) => {
    if (!isCancelled(value)) setError(value as Error)
    if (value instanceof ApiError && value.status === 409) setConflict(true)
  }
  const save = async () => {
    if (!draft || busy || settingsBusy || length > data.maxCharacters) return
    setBusy(true)
    setError('')
    try {
      resource.set(await saveMemoryDocument(draft.markdown, expected!))
      cancel()
    } catch (value) {
      failure(value)
    } finally {
      setBusy(false)
    }
  }
  const clear = async () => {
    if (busy || !window.confirm('清空已保存的所有记忆？聊天原文仍保留，记忆开关不会改变。')) return
    setBusy(true)
    setError('')
    try {
      resource.set(await clearMemoryDocument(data.revision))
      cancel()
    } catch (value) {
      failure(value)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className={styles.document}>
      <div className={styles.heading}>
        <h2>我的记忆</h2>
        {!draft && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setDraft('memory', {
                markdown: data.markdown,
                baseline: data.markdown,
                revision: data.revision,
              })
              setError('')
            }}
          >
            编辑
          </button>
        )}
      </div>
      <p className={styles.hint}>删除聊天不会同步删除已保存记忆，可在这里编辑或清空。</p>
      <p className={styles.updated}>
        最近更新：{data.updatedAt ? new Date(data.updatedAt).toLocaleString('zh-CN') : '暂无'}
      </p>
      <ErrorNotice>{error}</ErrorNotice>
      {draft ? (
        <>
          <MarkdownEditor
            label="记忆 Markdown"
            value={draft.markdown}
            disabled={busy}
            invalid={length > data.maxCharacters}
            describedBy="memory-length"
            onChange={(markdown) => setDraft('memory', { ...draft, markdown })}
            placeholder={'# 关于我\n\n可以写下希望 Noria 记住的背景、交流偏好或工作习惯。'}
            metadata={
              <span>
                {length} / {data.maxCharacters} 字符
              </span>
            }
          />
          <p id="memory-length" className={styles.hint}>
            {length > data.maxCharacters
              ? '内容超出容量，请缩短后保存；草稿不会被截断。'
              : '支持 Markdown 标题、段落和列表。未保存的内容不会用于对话。'}
          </p>
          <div className={styles.actions}>
            <BusyButton
              type="button"
              className={controls.primary}
              busy={busy}
              disabled={settingsBusy || length > data.maxCharacters || conflict}
              onClick={() => void save()}
            >
              保存
            </BusyButton>
            <button type="button" disabled={busy} onClick={cancel}>
              取消
            </button>
          </div>
        </>
      ) : data.markdown ? (
        <Markdown text={data.markdown} />
      ) : (
        <p className={styles.empty}>
          还没有记忆。可在对话中分享希望记住的偏好，也可以点“编辑”写下。
        </p>
      )}
      {conflict && (
        <section className={styles.conflict}>
          <p>已保留你的草稿。读取最新文档，合并后再保存。</p>
          <BusyButton
            type="button"
            busy={busy}
            onClick={async () => {
              setBusy(true)
              try {
                const current = await readMemory()
                setLatest(current)
                resource.set(current)
                setError('')
              } catch (value) {
                failure(value)
              } finally {
                setBusy(false)
              }
            }}
          >
            读取最新版本
          </BusyButton>
          {latest && (
            <>
              <h3>服务端最新内容</h3>
              <Markdown text={latest.markdown || '暂无内容'} />
              <p className={styles.hint}>核对并合并到上方草稿后，使用此版本继续保存。</p>
              <div className={styles.actions}>
                {draft && (
                  <button
                    type="button"
                    onClick={() => {
                      setDraft('memory', {
                        ...draft,
                        revision: latest.revision,
                        baseline: latest.markdown,
                      })
                      setConflict(false)
                      setLatest(null)
                    }}
                  >
                    已核对，保留草稿继续编辑
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    if (draft)
                      setDraft('memory', {
                        markdown: latest.markdown,
                        revision: latest.revision,
                        baseline: latest.markdown,
                      })
                    setConflict(false)
                    setLatest(null)
                  }}
                >
                  使用最新内容
                </button>
              </div>
            </>
          )}
        </section>
      )}
      {!draft && data.markdown && (
        <button
          type="button"
          className={controls.danger}
          disabled={busy || settingsBusy}
          onClick={() => void clear()}
        >
          清空记忆
        </button>
      )}
    </section>
  )
}
