// @vitest-environment jsdom
import type { AssistantInteraction, Conversation, ExecutionMode } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createRef, useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ExecutionModePicker } from '../../../apps/web/src/features/assistant/components/ExecutionModePicker'
import {
  QuestionPanel,
  QuestionHistory,
} from '../../../apps/web/src/features/assistant/components/QuestionPanel'
import { MessageComposer } from '../../../apps/web/src/features/assistant/components/MessageComposer'
import { useExecutionMode } from '../../../apps/web/src/features/assistant/hooks/useExecutionMode'
import { useConversationPersona } from '../../../apps/web/src/features/assistant/hooks/useConversationPersona'
import { useAssistantInteraction } from '../../../apps/web/src/features/assistant/hooks/useAssistantInteraction'
import {
  updateExecutionMode,
  answerInteraction,
  cancelInteraction,
} from '../../../apps/web/src/features/assistant/api/interactions'
import { messageSubmission } from '../../../apps/web/src/features/assistant/utils/files'
import { createVault, deferred, dialogs, identity, TestWorkspace } from './helpers'

vi.mock('@web/features/assistant/api/interactions', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/features/assistant/api/interactions')>()),
  updateExecutionMode: vi.fn(),
  answerInteraction: vi.fn(),
  cancelInteraction: vi.fn(),
}))
const conversation: Conversation = {
  id: 'first',
  title: '测试',
  personaId: 'professional',
  revision: 1,
  updatedAt: '2026-09-28T00:00:00Z',
}
const question: AssistantInteraction = {
  id: 'question',
  messageId: 'message',
  conversationId: 'first',
  taskId: 'task',
  revision: 1,
  state: 'waiting',
  createdAt: '2026-09-28T00:00:00Z',
  answers: [],
  questions: [
    {
      id: 'object',
      prompt: '要处理哪个项目？',
      type: 'single',
      allowCustom: true,
      options: [
        { id: 'a', label: '网站上线' },
        { id: 'b', label: '客户访谈' },
      ],
    },
    {
      id: 'scope',
      prompt: '包含哪些内容？',
      type: 'multiple',
      allowCustom: true,
      options: [
        { id: 'plan', label: '实施计划' },
        { id: 'risk', label: '风险说明' },
      ],
    },
    { id: 'date', prompt: '何时完成？', type: 'text', allowCustom: true, options: [] },
  ],
}
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ items: [] }))),
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
function choose(name: string) {
  fireEvent.click(screen.getByRole('button', { name: /^执行权限/ }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: new RegExp(`^${name}`) }))
}
function ModeHarness({ value = null }: { value?: Conversation | null }) {
  const persona = useConversationPersona(value?.id, value, vi.fn())
  const mode = useExecutionMode(value?.id, value, persona.interaction, vi.fn())
  return (
    <>
      <ExecutionModePicker
        value={mode.selected}
        disabled={mode.disabled}
        acknowledged={mode.acknowledged}
        onChange={(value, ack) => void mode.choose(value, ack)}
      />
      {mode.error && <p role="alert">{String(mode.error)}</p>}
    </>
  )
}
it('requires the full-mode explanation once and keeps keyboard navigation and focus return', () => {
  function Picker() {
    const [value, setValue] = useState<ExecutionMode>('auto'),
      [acknowledged, setAck] = useState(false)
    return (
      <ExecutionModePicker
        value={value}
        acknowledged={acknowledged}
        onChange={(mode, ack) => {
          setValue(mode)
          if (ack) setAck(true)
        }}
      />
    )
  }
  render(<Picker />)
  const trigger = screen.getByRole('button', { name: '执行权限：自动审核' })
  fireEvent.keyDown(trigger, { key: 'ArrowDown' })
  expect(document.activeElement).toBe(screen.getByRole('menuitemradio', { name: /自动审核/ }))
  fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' })
  expect(document.activeElement).toBe(screen.getByRole('menuitemradio', { name: /自主执行/ }))
  fireEvent.click(document.activeElement!)
  expect(screen.getByRole('dialog')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '开启自主执行' }))
  expect(trigger.getAttribute('aria-label')).toBe('执行权限：自主执行')
  choose('自动审核')
  choose('自主执行')
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(trigger)
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
  expect(document.activeElement).toBe(trigger)
})
it('keeps new-conversation mode in the account draft and freezes it in the first send body', () => {
  const vault = createVault()
  const view = (account = identity) => (
    <TestWorkspace vault={vault} account={account}>
      <ModeHarness />
    </TestWorkspace>
  )
  const mounted = render(view())
  choose('逐项确认')
  const draft = vault.getSnapshot()['composer:new'] as Parameters<typeof messageSubmission>[0]
  expect(messageSubmission({ ...draft, text: '创建工作', key: 'key' }).body).toMatchObject({
    executionMode: 'ask',
    newConversation: true,
    fullAccessConfirmed: false,
  })
  mounted.unmount()
  render(view())
  expect(screen.getByRole('button', { name: '执行权限：逐项确认' })).toBeTruthy()
  expect(updateExecutionMode).not.toHaveBeenCalled()
  cleanup()
  const other = { ...identity, member: { ...identity.member, id: 'another' } }
  vault.resume(other)
  render(view(other))
  expect(screen.getByRole('button', { name: '执行权限：自动审核' })).toBeTruthy()
})
it('saves existing mode with the conversation revision, rolls back failed changes and ignores late account results', async () => {
  const vault = createVault(),
    request = deferred<Conversation>()
  vi.mocked(updateExecutionMode)
    .mockRejectedValueOnce(new Error('保存失败'))
    .mockReturnValueOnce(request.promise)
  const view = (account = identity) => (
    <TestWorkspace vault={vault} account={account}>
      <ModeHarness value={conversation} />
    </TestWorkspace>
  )
  const mounted = render(view())
  choose('逐项确认')
  await screen.findByRole('alert')
  expect(screen.getByRole('button', { name: '执行权限：自动审核' })).toBeTruthy()
  expect(updateExecutionMode).toHaveBeenCalledWith(conversation, 'ask', false)
  choose('逐项确认')
  const other = { ...identity, member: { ...identity.member, id: 'another' } }
  act(() => vault.resume(other))
  mounted.rerender(view(other))
  await act(async () => request.resolve({ ...conversation, executionMode: 'ask', revision: 2 }))
  expect(screen.getByRole('button', { name: '执行权限：自动审核' })).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})
it('keeps the exact toolbar groups, same microphone slot, and disables mode without removing its button', () => {
  const props = {
    containerRef: createRef<HTMLDivElement>(),
    send: vi.fn(),
    addFiles: vi.fn(),
    composer: { text: '', files: [], key: '' },
    locked: false,
    change: vi.fn(),
    textInput: createRef<HTMLTextAreaElement>(),
    busy: false,
    previewUploading: false,
    pending: false,
    sendError: '',
    retryWait: 0,
    children: null,
    executionControl: <ExecutionModePicker value="auto" acknowledged={false} onChange={vi.fn()} />,
    recording: { state: 'idle' as const, seconds: 0, start: vi.fn(), stop: vi.fn() },
  }
  const view = render(<MessageComposer {...props} />)
  const attach = screen.getByRole('button', { name: '添加附件' })
  expect(
    within(attach.parentElement!)
      .getAllByRole('button')
      .map((button) => button.getAttribute('aria-label'))
      .filter(Boolean),
  ).toEqual(['添加附件', '执行权限：自动审核'])
  const mic = screen.getByRole('button', { name: '录制语音' })
  const controls = () =>
    within(mic.parentElement!)
      .getAllByRole('button')
      .map((button) => button.getAttribute('aria-label'))
  expect(controls()).toEqual([expect.stringMatching(/^上下文使用情况/), '录制语音', '发送'])
  view.rerender(
    <MessageComposer
      {...props}
      recording={{ ...props.recording, state: 'recording', seconds: 15 }}
    />,
  )
  expect(screen.getByRole('button', { name: '停止录音 · 15 秒' })).toBe(mic)
  expect(controls()).toEqual([expect.stringMatching(/^上下文使用情况/), '停止录音 · 15 秒', '发送'])
})
function fillAnswers() {
  fireEvent.click(screen.getByLabelText('网站上线'))
  fireEvent.click(screen.getByLabelText('实施计划'))
  fireEvent.click(screen.getByLabelText('风险说明'))
  fireEvent.change(screen.getByRole('textbox', { name: '何时完成？ · 自由回答' }), {
    target: { value: '下周五' },
  })
}
it('supports single/multiple/free answers, validates missing fields, preserves drafts through collapse and remount', () => {
  const vault = createVault(),
    answer = vi.fn(),
    cancel = vi.fn()
  const view = () => (
    <TestWorkspace vault={vault}>
      <QuestionPanel item={question} busy={false} error="" onAnswer={answer} onCancel={cancel} />
    </TestWorkspace>
  )
  const mounted = render(view())
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }))
  expect(answer).not.toHaveBeenCalled()
  expect(screen.getByText(/请回答每个问题/)).toBeTruthy()
  fillAnswers()
  fireEvent.click(screen.getByRole('button', { name: '需要你补充 · 3 个问题' }))
  expect(screen.queryByRole('button', { name: '提交回答' })).toBeNull()
  mounted.unmount()
  render(view())
  fireEvent.click(screen.getByRole('button', { name: '需要你补充 · 3 个问题' }))
  expect(
    (screen.getByRole('textbox', { name: '何时完成？ · 自由回答' }) as HTMLTextAreaElement).value,
  ).toBe('下周五')
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }))
  expect(answer).toHaveBeenCalledWith([
    { questionId: 'object', optionIds: ['a'], text: '' },
    { questionId: 'scope', optionIds: ['plan', 'risk'], text: '' },
    { questionId: 'date', optionIds: [], text: '下周五' },
  ])
  fireEvent.click(screen.getByRole('button', { name: '取消本次任务' }))
  expect(cancel).toHaveBeenCalledTimes(1)
})
it('custom single-choice text clears its selected option rather than submitting conflicting choices', () => {
  const answer = vi.fn()
  render(
    <TestWorkspace vault={createVault()}>
      <QuestionPanel
        item={{ ...question, questions: question.questions.slice(0, 1) }}
        busy={false}
        error=""
        onAnswer={answer}
        onCancel={vi.fn()}
      />
    </TestWorkspace>,
  )
  fireEvent.click(screen.getByLabelText('网站上线'))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '先讨论新的项目' } })
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }))
  expect(answer).toHaveBeenCalledWith([
    { questionId: 'object', optionIds: [], text: '先讨论新的项目' },
  ])
})
it('shows completed questions as compact expandable history', () => {
  render(
    <QuestionHistory
      item={{
        ...question,
        state: 'answered',
        answers: [{ questionId: 'object', optionIds: ['a'], text: '' }],
      }}
    />,
  )
  expect(screen.getByText('已回答 · 3 个问题')).toBeTruthy()
  expect(document.querySelector('details')?.open).toBe(false)
  expect(screen.getByText('网站上线')).toBeTruthy()
})
function InteractionHarness({
  incoming = [question],
  continued,
}: {
  incoming?: AssistantInteraction[]
  continued: (value?: { conversationId: string; messageId: string; jobId: string }) => void
}) {
  const questions = useAssistantInteraction('first', incoming, continued)
  return questions.waiting ? (
    <QuestionPanel
      item={questions.waiting}
      busy={!!questions.busy}
      error={questions.error}
      onAnswer={(answers) => void questions.respond(questions.waiting!, answers)}
      onCancel={() => void questions.respond(questions.waiting!)}
    />
  ) : (
    <p>等待已结束</p>
  )
}
it('retries a lost answer with the same key, preserves input, resumes once and does not reopen from old snapshots', async () => {
  const continued = vi.fn(),
    incoming = [question],
    vault = createVault()
  const continuation = { conversationId: 'first', messageId: 'continued', jobId: 'job2' }
  vi.mocked(answerInteraction)
    .mockRejectedValueOnce(new Error('网络中断'))
    .mockResolvedValueOnce({
      interaction: { ...question, state: 'answered', revision: 2 },
      continuation,
    })
  render(
    <TestWorkspace vault={vault}>
      <InteractionHarness incoming={incoming} continued={continued} />
    </TestWorkspace>,
  )
  fillAnswers()
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }))
  await screen.findByText('网络中断')
  expect(vault.getSnapshot()['question:question:1']).toBeTruthy()
  expect(
    (screen.getByRole('textbox', { name: '何时完成？ · 自由回答' }) as HTMLTextAreaElement).value,
  ).toBe('下周五')
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }))
  await screen.findByText('等待已结束')
  expect(vi.mocked(answerInteraction).mock.calls[0][2]).toBe(
    vi.mocked(answerInteraction).mock.calls[1][2],
  )
  expect(continued).toHaveBeenCalledExactlyOnceWith(continuation)
  expect(vault.getSnapshot()['question:question:1']).toBeUndefined()
})
it('cancels waiting questions without submitting an answer', async () => {
  vi.mocked(cancelInteraction).mockResolvedValue({
    interaction: { ...question, state: 'cancelled', revision: 2 },
  })
  const continued = vi.fn(),
    vault = createVault()
  vault.writer()('composer:first', { text: '继续保留其他输入' })
  render(
    <TestWorkspace vault={vault}>
      <InteractionHarness continued={continued} />
    </TestWorkspace>,
  )
  fillAnswers()
  fireEvent.click(screen.getByRole('button', { name: '取消本次任务' }))
  await screen.findByText('等待已结束')
  expect(answerInteraction).not.toHaveBeenCalled()
  expect(continued).toHaveBeenCalledExactlyOnceWith(undefined)
  expect(vault.getSnapshot()).toEqual({ 'composer:first': { text: '继续保留其他输入' } })
})
it.each(['answered', 'cancelled', 'expired'] as const)(
  'releases only the matching question draft when a server snapshot becomes %s',
  async (state) => {
    const vault = createVault()
    vault.writer()('question:another:1', { answers: {} })
    const view = (incoming: AssistantInteraction[]) => (
      <TestWorkspace vault={vault}>
        <InteractionHarness incoming={incoming} continued={vi.fn()} />
      </TestWorkspace>
    )
    const mounted = render(view([question]))
    fillAnswers()
    expect(vault.getSnapshot()['question:question:1']).toBeTruthy()
    mounted.rerender(view([{ ...question, state, revision: 2 }]))
    await waitFor(() => expect(vault.getSnapshot()['question:question:1']).toBeUndefined())
    expect(vault.getSnapshot()['question:another:1']).toEqual({ answers: {} })
  },
)
it('does not apply an old response after account changes', async () => {
  const request = deferred<Awaited<ReturnType<typeof answerInteraction>>>(),
    continued = vi.fn(),
    vault = createVault()
  vi.mocked(answerInteraction).mockReturnValue(request.promise)
  const view = (account = identity) => (
    <TestWorkspace vault={vault} account={account}>
      <InteractionHarness continued={continued} />
    </TestWorkspace>
  )
  const mounted = render(view())
  fillAnswers()
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }))
  const other = { ...identity, member: { ...identity.member, id: 'other' } }
  act(() => vault.resume(other))
  mounted.rerender(view(other))
  await act(async () =>
    request.resolve({
      interaction: { ...question, state: 'answered', revision: 2 },
      continuation: { conversationId: 'first', messageId: 'continued', jobId: 'job' },
    }),
  )
  expect(continued).not.toHaveBeenCalled()
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '提交回答' }).hasAttribute('disabled')).toBe(false),
  )
})

it('redacts a revoked source even when its server projection has the same revision as a saved answer', async () => {
  const resolved = {
    ...question,
    state: 'answered' as const,
    revision: 2,
    answers: [{ questionId: 'object', optionIds: ['a'], text: '内部计划' }],
  }
  let records: AssistantInteraction[] = []
  vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({ items: records })))
  vi.mocked(answerInteraction).mockResolvedValue({ interaction: resolved })
  function Recovery() {
    const result = useAssistantInteraction('first', [question], vi.fn())
    return (
      <>
        <button onClick={() => void result.respond(question, resolved.answers)}>回答</button>
        <output>{JSON.stringify(result.items)}</output>
      </>
    )
  }
  render(
    <TestWorkspace vault={createVault()}>
      <Recovery />
    </TestWorkspace>,
  )
  fireEvent.click(screen.getByRole('button', { name: '回答' }))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('内部计划'))
  records = [{ ...resolved, state: 'expired', questions: [], answers: [] }]
  act(() => window.dispatchEvent(new Event('online')))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('expired'))
  expect(screen.getByRole('status').textContent).not.toContain('内部计划')
  expect(screen.getByRole('status').textContent).not.toContain('网站上线')
})
