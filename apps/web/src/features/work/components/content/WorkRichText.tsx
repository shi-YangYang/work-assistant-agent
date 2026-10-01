import type { Attachment, Work, WorkDocument } from '@paa/api-contracts'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import UniqueID from '@tiptap/extension-unique-id'
import { Bold, List, ListChecks, Heading2, Link2, Paperclip } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { fileAccept } from '@web/utils/attachments'
import { MaterialContext, WorkMaterialNode } from './MaterialNode'
import styles from './WorkContent.module.css'

export function WorkRichText({
  body,
  change,
  work,
  pending = [],
  upload,
  disabled = false,
  own = false,
}: {
  body: WorkDocument
  change?: (body: WorkDocument) => void
  work?: Work
  pending?: Attachment[]
  upload?: (files: File[]) => Promise<Attachment[]>
  disabled?: boolean
  own?: boolean
}) {
  const files = useRef<HTMLInputElement>(null)
  const [link, setLink] = useState<string | null>(null)
  const [invalidLink, setInvalidLink] = useState(false)
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        underline: false,
        link: { openOnClick: !change, protocols: ['http', 'https', 'mailto'] },
      }),
      TaskList,
      TaskItem.configure({ nested: true }),
      WorkMaterialNode,
      UniqueID.configure({
        types: [
          'paragraph',
          'heading',
          'bulletList',
          'orderedList',
          'taskList',
          'blockquote',
          'codeBlock',
          'horizontalRule',
          'material',
        ],
      }),
    ],
    content: { type: 'doc', content: body.content.length ? body.content : [{ type: 'paragraph' }] },
    editable: !!change && !disabled,
    shouldRerenderOnTransaction: true,
    editorProps: {
      attributes: { role: 'textbox', 'aria-label': '工作正文', 'aria-multiline': 'true' },
      handlePaste: (_, event) => {
        const pasted = Array.from(event.clipboardData?.files ?? [])
        if (!upload || !pasted.length || disabled) return false
        void add(pasted)
        return true
      },
      handleDrop: (_, event) => {
        const dropped = Array.from(event.dataTransfer?.files ?? [])
        if (!upload || !dropped.length || disabled) return false
        void add(dropped)
        return true
      },
    },
    onUpdate: ({ editor }) =>
      change?.({ schemaVersion: 1, content: editor.getJSON().content ?? [] }),
  })
  async function add(selected: File[]) {
    const uploaded = await upload?.(selected)
    if (editor && !editor.isDestroyed && uploaded?.length)
      editor
        .chain()
        .focus()
        .insertContent(
          uploaded.map((file) => ({ type: 'material', attrs: { materialId: file.id } })),
        )
        .run()
  }
  const editable = !!change && !disabled
  useEffect(() => {
    editor?.setEditable(editable, false)
  }, [editor, editable])
  // External replacements are explicit conflict recovery; ordinary typing does not reset selection.
  useEffect(() => {
    if (!editor || editor.isDestroyed) return
    const content = body.content.length ? body.content : [{ type: 'paragraph' }]
    if (JSON.stringify(editor.getJSON().content) !== JSON.stringify(content))
      editor.commands.setContent({ type: 'doc', content }, { emitUpdate: false })
  }, [body, editor])
  return (
    <MaterialContext.Provider value={{ work, pending, own }}>
      <div className={styles.rich} data-editing={!!change}>
        {change && (
          <div className={styles.toolbar} role="toolbar" aria-label="正文格式">
            <button
              type="button"
              disabled={disabled}
              title="加粗"
              aria-label="加粗"
              aria-pressed={editor?.isActive('bold')}
              onClick={() => editor?.chain().focus().toggleBold().run()}
            >
              <Bold size={17} />
            </button>
            <button
              type="button"
              disabled={disabled}
              title="小标题"
              aria-label="小标题"
              aria-pressed={editor?.isActive('heading')}
              onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
            >
              <Heading2 size={18} />
            </button>
            <button
              type="button"
              disabled={disabled}
              title="列表"
              aria-label="列表"
              aria-pressed={editor?.isActive('bulletList')}
              onClick={() => editor?.chain().focus().toggleBulletList().run()}
            >
              <List size={18} />
            </button>
            <button
              type="button"
              disabled={disabled}
              title="勾选清单"
              aria-label="勾选清单"
              aria-pressed={editor?.isActive('taskList')}
              onClick={() => editor?.chain().focus().toggleTaskList().run()}
            >
              <ListChecks size={18} />
            </button>
            <button
              type="button"
              disabled={disabled}
              title="链接"
              aria-label="链接"
              onClick={() => {
                setInvalidLink(false)
                setLink(editor?.getAttributes('link').href ?? '')
              }}
            >
              <Link2 size={17} />
            </button>
            {upload && (
              <button type="button" disabled={disabled} onClick={() => files.current?.click()}>
                <Paperclip size={16} />
                添加材料
              </button>
            )}
            <input
              hidden
              type="file"
              multiple
              ref={files}
              accept={fileAccept}
              aria-label="正文材料"
              onChange={(event) => {
                void add(Array.from(event.target.files ?? []))
                event.target.value = ''
              }}
            />
          </div>
        )}
        {link !== null && (
          <div className={styles.linkEditor}>
            <input
              aria-label="链接地址"
              placeholder="https://…"
              value={link}
              onChange={(event) => setLink(event.target.value)}
            />
            <button
              type="button"
              onClick={() => {
                if (link && !/^(https?:\/\/|mailto:)/i.test(link)) {
                  setInvalidLink(true)
                  return
                }
                if (link)
                  editor?.chain().focus().extendMarkRange('link').setLink({ href: link }).run()
                else editor?.chain().focus().unsetLink().run()
                setLink(null)
              }}
            >
              确定
            </button>
            <button type="button" onClick={() => setLink(null)}>
              取消
            </button>
            {invalidLink && <small role="alert">请输入 http、https 或 mailto 链接</small>}
          </div>
        )}
        <EditorContent editor={editor} />
      </div>
    </MaterialContext.Provider>
  )
}
