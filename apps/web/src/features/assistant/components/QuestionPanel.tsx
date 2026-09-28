import type { AssistantInteraction } from '@paa/api-contracts'
import type { InteractionAnswer } from '../api/interactions'
import { useWorkspace } from '@web/lib/workspace'
import { useId, useState } from 'react'
import { ChevronDown, MessageCircleQuestion } from 'lucide-react'
import { ErrorNotice } from '@web/components/ErrorNotice'
import controlsStyles from '../../../styles/controls.module.css'
import styles from './QuestionPanel.module.css'

type AnswerDraft = { answers: Record<string, InteractionAnswer>; collapsed?: boolean }
export function QuestionPanel({
  item,
  busy,
  disabled = false,
  error,
  onAnswer,
  onCancel,
}: {
  item: AssistantInteraction
  busy: boolean
  disabled?: boolean
  error: Error | string
  onAnswer: (answers: InteractionAnswer[]) => void
  onCancel: () => void
}) {
  const { drafts, setDraft } = useWorkspace()
  const key = `question:${item.id}:${item.revision}`
  const draft = drafts[key] as AnswerDraft | undefined
  const [validation, setValidation] = useState('')
  const id = useId()
  const expanded = !draft?.collapsed
  const update = (questionId: string, patch: Partial<InteractionAnswer>) => {
    setValidation('')
    setDraft(key, (previous: AnswerDraft | undefined) => ({
      ...previous,
      answers: {
        ...previous?.answers,
        [questionId]: {
          questionId,
          optionIds: [],
          text: '',
          ...previous?.answers[questionId],
          ...patch,
        },
      },
    }))
  }
  return (
    <section className={styles.panel} aria-label="回答助手问题">
      <button
        type="button"
        className={styles.heading}
        aria-expanded={expanded}
        aria-controls={id}
        onClick={() =>
          setDraft(key, { ...draft, answers: draft?.answers ?? {}, collapsed: expanded })
        }
      >
        <MessageCircleQuestion size={17} aria-hidden="true" />
        <span>
          需要你补充{item.questions.length > 1 ? ` · ${item.questions.length} 个问题` : ''}
        </span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      <div id={id} hidden={!expanded} className={styles.body}>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (busy || disabled) return
            const answers = item.questions.map(
              (question) =>
                draft?.answers[question.id] ?? { questionId: question.id, optionIds: [], text: '' },
            )
            if (answers.some((answer) => !answer.optionIds.length && !answer.text.trim())) {
              setValidation('请回答每个问题，也可以输入自己的答案。')
              return
            }
            onAnswer(answers)
          }}
        >
          <div className={styles.questions}>
            {item.questions.map((question) => {
              const answer = draft?.answers[question.id]
              return (
                <fieldset key={question.id} disabled={busy || disabled}>
                  <legend>{question.prompt}</legend>
                  {!!question.options.length && (
                    <div className={styles.options}>
                      {question.options.map((option) => (
                        <label
                          key={option.id}
                          data-selected={answer?.optionIds.includes(option.id) || false}
                        >
                          <input
                            type={question.type === 'multiple' ? 'checkbox' : 'radio'}
                            name={`${id}-${question.id}`}
                            value={option.id}
                            checked={answer?.optionIds.includes(option.id) || false}
                            onChange={(event) =>
                              update(question.id, {
                                optionIds:
                                  question.type === 'multiple'
                                    ? event.target.checked
                                      ? [...(answer?.optionIds ?? []), option.id]
                                      : (answer?.optionIds ?? []).filter(
                                          (value) => value !== option.id,
                                        )
                                    : [option.id],
                                text: question.type === 'single' ? '' : (answer?.text ?? ''),
                              })
                            }
                          />
                          <span>
                            {option.label}
                            {option.description && <small>{option.description}</small>}
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                  {(question.allowCustom || question.type === 'text') && (
                    <label className={styles.custom}>
                      <span>{question.options.length ? '或填写其他答案' : '你的回答'}</span>
                      <textarea
                        aria-label={`${question.prompt} · 自由回答`}
                        rows={2}
                        maxLength={2000}
                        value={answer?.text ?? ''}
                        onChange={(event) =>
                          update(question.id, {
                            text: event.target.value,
                            ...(question.type === 'single' ? { optionIds: [] } : {}),
                          })
                        }
                      />
                    </label>
                  )}
                </fieldset>
              )
            })}
          </div>
          <ErrorNotice>{validation || error}</ErrorNotice>
          <div className={styles.actions}>
            <button type="button" disabled={busy || disabled} onClick={onCancel}>
              取消本次任务
            </button>
            <button
              type="submit"
              className={controlsStyles.primary}
              disabled={busy || disabled}
              aria-busy={busy}
            >
              {busy ? '正在提交' : '提交回答'}
            </button>
          </div>
        </form>
      </div>
    </section>
  )
}

export function QuestionHistory({ item }: { item: AssistantInteraction }) {
  const labels = { waiting: '等待回答', answered: '已回答', cancelled: '已取消', expired: '已失效' }
  return (
    <details className={styles.history}>
      <summary>
        {labels[item.state]}
        {item.questions.length ? ` · ${item.questions.length} 个问题` : ''}
      </summary>
      {item.questions.map((question) => {
        const answer = item.answers.find((value) => value.questionId === question.id)
        return (
          <div key={question.id}>
            <strong>{question.prompt}</strong>
            <p>
              {answer
                ? [
                    ...answer.optionIds
                      .map((id) => question.options.find((option) => option.id === id)?.label)
                      .filter(Boolean),
                    answer.text,
                  ]
                    .filter(Boolean)
                    .join('；')
                : '尚未回答'}
            </p>
          </div>
        )
      })}
    </details>
  )
}
