import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Bold, Code2, Eye, Heading2, Italic, Link2, List, ListOrdered, Pencil } from 'lucide-react'
import { Markdown } from '@web/components/content/Markdown'
import { formatMarkdown, type MarkdownFormat } from './formatting'
import styles from './MarkdownEditor.module.css'

const formats = [
  { format: 'heading', label: '小标题', icon: Heading2 },
  { format: 'bold', label: '加粗', icon: Bold },
  { format: 'italic', label: '斜体', icon: Italic },
  { format: 'bullet', label: '无序列表', icon: List },
  { format: 'ordered', label: '有序列表', icon: ListOrdered },
  { format: 'link', label: '链接', icon: Link2 },
  { format: 'code', label: '代码块', icon: Code2 },
] as const

export function MarkdownEditor({
  value,
  onChange,
  label,
  describedBy,
  placeholder,
  disabled = false,
  invalid = false,
  metadata,
}: {
  value: string
  onChange: (value: string) => void
  label: string
  describedBy?: string
  placeholder?: string
  disabled?: boolean
  invalid?: boolean
  metadata?: ReactNode
}) {
  const textarea = useRef<HTMLTextAreaElement>(null)
  const selection = useRef<{ start: number; end: number; scrollTop: number } | null>(null)
  const [preview, setPreview] = useState(false)
  useLayoutEffect(() => {
    const next = selection.current
    const input = textarea.current
    if (!next || !input) return
    input.focus({ preventScroll: true })
    input.setSelectionRange(next.start, next.end)
    input.scrollTop = next.scrollTop
    selection.current = null
  }, [value])
  const apply = (format: MarkdownFormat) => {
    const input = textarea.current
    if (!input || disabled || preview) return
    const next = formatMarkdown(value, input.selectionStart, input.selectionEnd, format)
    selection.current = { ...next, scrollTop: input.scrollTop }
    onChange(next.value)
  }
  return (
    <div className={styles.editor} data-invalid={invalid}>
      <div className={styles.header}>
        <div className={styles.tools} role="group" aria-label="Markdown 格式">
          {formats.map(({ format, label: title, icon: Icon }) => (
            <button
              key={format}
              type="button"
              aria-label={title}
              title={title}
              disabled={disabled || preview}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => apply(format)}
            >
              <Icon size={17} aria-hidden="true" />
            </button>
          ))}
        </div>
        <button
          type="button"
          className={styles.mode}
          aria-pressed={preview}
          onClick={() => setPreview(!preview)}
        >
          {preview ? <Pencil size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
          {preview ? '继续编辑' : '预览'}
        </button>
      </div>
      <textarea
        ref={textarea}
        className={styles.source}
        hidden={preview}
        aria-label={label}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        disabled={disabled}
        value={value}
        placeholder={placeholder}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing || event.altKey || !(event.metaKey || event.ctrlKey))
            return
          const key = event.key.toLowerCase()
          if (key !== 'b' && key !== 'i') return
          event.preventDefault()
          apply(key === 'b' ? 'bold' : 'italic')
        }}
      />
      {preview && (
        <div className={styles.preview} role="region" aria-label={`${label}预览`} tabIndex={0}>
          <Markdown text={value || '暂无内容'} />
        </div>
      )}
      <div className={styles.footer}>
        <span>Markdown</span>
        {metadata}
      </div>
    </div>
  )
}
