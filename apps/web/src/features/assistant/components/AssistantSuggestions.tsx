import { ArrowUpRight, ClipboardList, FileText, Sparkles } from 'lucide-react'
import styles from './AssistantSuggestions.module.css'

export function AssistantSuggestions({
  admin,
  disabled,
  onChoose,
}: {
  admin: boolean
  disabled: boolean
  onChoose: (text: string) => void
}) {
  const suggestions = admin
    ? [
        { title: '梳理工作', detail: '关注团队遇到的阻碍', text: '团队当前有哪些阻碍？' },
        { title: '工作进展', detail: '了解本周的工作变化', text: '本周员工有哪些工作进展？' },
        { title: '整理汇报', detail: '让进展清晰可见', text: '查看最近提交的周报' },
      ]
    : [
        { title: '梳理工作', detail: '把待办变成下一步', text: '帮我创建工作：' },
        { title: '整理汇报', detail: '让进展清晰可见', text: '生成今天的日报' },
        { title: '汇报待办', detail: '查看还需提交的报告', text: '查看我还没交的报告' },
      ]
  return (
    <div className={styles['suggestions']}>
      {suggestions.map(({ title, detail, text }, index) => (
        <button key={text} disabled={disabled} onClick={() => onChoose(text)}>
          <span className={styles['shortcut-icon']}>
            {index === 0 ? (
              <ClipboardList size={18} />
            ) : index === 1 ? (
              <Sparkles size={18} />
            ) : (
              <FileText size={18} />
            )}
          </span>
          <strong>{title}</strong>
          <small>{detail}</small>
          <ArrowUpRight size={14} />
        </button>
      ))}
    </div>
  )
}
