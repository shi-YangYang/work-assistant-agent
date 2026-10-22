import type { AssistantInteraction } from '@paa/api-contracts'
import type { InteractionAnswer } from '../../api/interactions'
import { useWorkspace } from '@web/lib/workspace'
import { useId, useState } from 'react'
import { ChevronDown, MessageCircleQuestion } from 'lucide-react'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import controlsStyles from '../../../../styles/controls.module.css'
import styles from './QuestionPanel.module.css'

type AnswerDraft = {
  answers: Record<string, InteractionAnswer>
  collapsed?: boolean
  currentQuestionId?: string
}
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
  const currentIndex = Math.max(
    0,
    item.questions.findIndex((question) => question.id === draft?.currentQuestionId),
  )
  const lastQuestion = currentIndex >= item.questions.length - 1
  const navigate = (index: number) => {
    setValidation('')
    setDraft(key, (previous: AnswerDraft | undefined) => ({
      ...previous,
      answers: previous?.answers ?? {},
      currentQuestionId: item.questions[index]?.id,
    }))
  }
  const update = (questionId: string, patch: Partial<InteractionAnswer>, advance = false) => {
    setValidation('')
    setDraft(key, (previous: AnswerDraft | undefined) => ({
      ...previous,
      ...(advance && !lastQuestion
        ? { currentQuestionId: item.questions[currentIndex + 1].id }
        : {}),
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
            if (!lastQuestion) {
              const answer = draft?.answers[item.questions[currentIndex].id]
              if (answer && answer.optionIds.length > 1) {
                setValidation('请重新选择一个选项。')
                return
              }
              if (!answer?.optionIds.length && !answer?.text.trim()) {
                setValidation('请回答当前问题，也可以输入自己的答案。')
                return
              }
              navigate(currentIndex + 1)
              return
            }
            const answers = item.questions.map(
              (question) =>
                draft?.answers[question.id] ?? { questionId: question.id, optionIds: [], text: '' },
            )
            const missingIndex = answers.findIndex(
              (answer) =>
                answer.optionIds.length > 1 || (!answer.optionIds.length && !answer.text.trim()),
            )
            if (missingIndex !== -1) {
              navigate(missingIndex)
              setValidation(
                answers[missingIndex].optionIds.length > 1
                  ? '请重新选择一个选项。'
                  : '请回答当前问题，也可以输入自己的答案。',
              )
              return
            }
            onAnswer(answers)
          }}
        >
          {item.questions.length > 1 && (
            <p className={styles.progress} role="status">
              第 {currentIndex + 1} / {item.questions.length} 题
            </p>
          )}
          <div className={styles.questions} key={item.questions[currentIndex]?.id}>
            {item.questions.slice(currentIndex, currentIndex + 1).map((question) => {
              const answer = draft?.answers[question.id]
              return (
                <fieldset key={question.id} disabled={busy || disabled}>
                  <legend>{question.prompt}</legend>
                  {!!question.options.length && (
                    <div className={styles.options}>
                      {question.options.map((option) => (
                        <label
                          key={option.id}
                          data-selected={
                            answer?.optionIds.length === 1 && answer.optionIds[0] === option.id
                          }
                        >
                          <input
                            type="radio"
                            name={`${id}-${question.id}`}
                            value={option.id}
                            checked={
                              answer?.optionIds.length === 1 && answer.optionIds[0] === option.id
                            }
                            onClick={() => {
                              if (
                                answer?.optionIds.length === 1 &&
                                answer.optionIds[0] === option.id &&
                                !lastQuestion
                              ) {
                                navigate(currentIndex + 1)
                              }
                            }}
                            onChange={() =>
                              update(question.id, { optionIds: [option.id], text: '' }, true)
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
                            optionIds: [],
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
            <button
              type="button"
              className={styles.cancel}
              disabled={busy || disabled}
              onClick={onCancel}
            >
              取消本次任务
            </button>
            {item.questions.length > 1 && (
              <button
                type="button"
                disabled={busy || disabled || currentIndex === 0}
                onClick={() => navigate(currentIndex - 1)}
              >
                上一个
              </button>
            )}
            <button
              type="submit"
              className={controlsStyles.primary}
              disabled={busy || disabled}
              aria-busy={busy}
            >
              {busy ? '正在提交' : lastQuestion ? '提交回答' : '下一个'}
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
