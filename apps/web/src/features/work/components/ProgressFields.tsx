import type { Progress } from '@paa/api-contracts'
import { AutoTextarea } from '@web/components/AutoTextarea'
import { FormField } from '@web/components/FormField'

export function ProgressFields({
  value,
  change,
  errors = {},
}: {
  value: Progress
  change: (value: Progress) => void
  errors?: Partial<Record<keyof Progress, string>>
}) {
  return (
    <>
      <FormField
        label="工作事项"
        value={value.title}
        required
        maxLength={200}
        error={errors.title}
        onChange={(e) => change({ ...value, title: e.target.value })}
      />
      <label>
        当前进展
        <AutoTextarea
          rows={3}
          value={value.summary}
          maxLength={4000}
          aria-invalid={errors.summary ? true : undefined}
          onChange={(e) => change({ ...value, summary: e.target.value })}
        />
        {errors.summary && (
          <small className="form-field-error" role="alert">
            {errors.summary}
          </small>
        )}
      </label>
      <label>
        状态
        <select
          value={value.status}
          aria-invalid={errors.status ? true : undefined}
          onChange={(e) => change({ ...value, status: e.target.value as Progress['status'] })}
        >
          <option value="in_progress">进行中</option>
          <option value="blocked">有阻碍</option>
          <option value="done">整个事项已完成</option>
        </select>
        {errors.status && (
          <small className="form-field-error" role="alert">
            {errors.status}
          </small>
        )}
      </label>
      <label>
        截止日期（选填）
        <input
          type="date"
          max="9999-12-31"
          aria-invalid={errors.dueDate ? true : undefined}
          value={value.dueDate ?? ''}
          onClick={(event) => event.currentTarget.showPicker?.()}
          onChange={(event) => change({ ...value, dueDate: event.target.value || null })}
        />
        {errors.dueDate && (
          <small className="form-field-error" role="alert">
            {errors.dueDate}
          </small>
        )}
      </label>
      <label>
        问题或阻碍
        <AutoTextarea
          rows={2}
          value={value.blocker}
          maxLength={2000}
          aria-invalid={errors.blocker ? true : undefined}
          onChange={(e) => change({ ...value, blocker: e.target.value })}
        />
        {errors.blocker && (
          <small className="form-field-error" role="alert">
            {errors.blocker}
          </small>
        )}
      </label>
      <label>
        下一步
        <AutoTextarea
          rows={2}
          value={value.nextStep}
          maxLength={2000}
          aria-invalid={errors.nextStep ? true : undefined}
          onChange={(e) => change({ ...value, nextStep: e.target.value })}
        />
        {errors.nextStep && (
          <small className="form-field-error" role="alert">
            {errors.nextStep}
          </small>
        )}
      </label>
    </>
  )
}
