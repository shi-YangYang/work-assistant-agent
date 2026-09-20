import type { Progress } from '@paa/api-contracts'
import { AutoTextarea } from '@web/components/AutoTextarea'

export function ProgressFields({
  value,
  change,
}: {
  value: Progress
  change: (value: Progress) => void
}) {
  return (
    <>
      <label>
        工作事项
        <input
          value={value.title}
          required
          maxLength={200}
          onChange={(e) => change({ ...value, title: e.target.value })}
        />
      </label>
      <label>
        当前进展
        <AutoTextarea
          rows={3}
          value={value.summary}
          maxLength={4000}
          onChange={(e) => change({ ...value, summary: e.target.value })}
        />
      </label>
      <label>
        状态
        <select
          value={value.status}
          onChange={(e) => change({ ...value, status: e.target.value as Progress['status'] })}
        >
          <option value="in_progress">进行中</option>
          <option value="blocked">有阻碍</option>
          <option value="done">整个事项已完成</option>
        </select>
      </label>
      <label>
        截止日期（选填）
        <input
          type="date"
          value={value.dueDate ?? ''}
          onClick={(event) => event.currentTarget.showPicker?.()}
          onChange={(event) => change({ ...value, dueDate: event.target.value || null })}
        />
      </label>
      <label>
        问题或阻碍
        <AutoTextarea
          rows={2}
          value={value.blocker}
          maxLength={2000}
          onChange={(e) => change({ ...value, blocker: e.target.value })}
        />
      </label>
      <label>
        下一步
        <AutoTextarea
          rows={2}
          value={value.nextStep}
          maxLength={2000}
          onChange={(e) => change({ ...value, nextStep: e.target.value })}
        />
      </label>
    </>
  )
}
