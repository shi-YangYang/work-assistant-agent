// @vitest-environment jsdom
import type {
  AssistantInteraction,
  Conversation,
  ExecutionMode,
  ExecutionSettings,
} from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createRef, useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ExecutionModePicker } from '../../../../apps/web/src/features/assistant/components/composer/controls/ExecutionModePicker'
import {
  QuestionPanel,
  QuestionHistory,
} from '../../../../apps/web/src/features/assistant/components/interactions/QuestionPanel'
import { MessageComposer } from '../../../../apps/web/src/features/assistant/components/composer/MessageComposer'
import { useExecutionMode } from '../../../../apps/web/src/features/assistant/hooks/preferences/useExecutionMode'
import { useConversationPersona } from '../../../../apps/web/src/features/assistant/hooks/preferences/useConversationPersona'
import { useAssistantInteraction } from '../../../../apps/web/src/features/assistant/hooks/conversation/useAssistantInteraction'
import {
  updateExecutionMode,
  answerInteraction,
  cancelInteraction,
} from '../../../../apps/web/src/features/assistant/api/interactions'
import { clearQueryResources } from '../../../../apps/web/src/lib/query-resource'
import { messageSubmission } from '../../../../apps/web/src/features/assistant/utils/files'
import { createVault, deferred, dialogs, identity, TestWorkspace } from '../helpers'

vi.mock('@web/features/assistant/api/interactions', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/features/assistant/api/interactions')>()),
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
let storedMode: ExecutionSettings
beforeEach(() => {
  dialogs()
  vi.resetAllMocks()
  storedMode = { executionMode: 'auto', modeRevision: 1, fullAccessConfirmed: false }
  vi.mocked(updateExecutionMode).mockImplementation(async (previous, mode, ack) => {
    storedMode = {
      executionMode: mode,
      modeRevision: previous.modeRevision + 1,
      fullAccessConfirmed: previous.fullAccessConfirmed || ack,
    }
    return storedMode
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/assistant/execution-settings') ? storedMode : { items: [] },
          ),
        ),
    ),
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
  const mode = useExecutionMode(persona.interaction)
  return (
    <>
      <ExecutionModePicker
        value={mode.selected}
        disabled={mode.disabled}
        acknowledged={mode.acknowledged}
        onChange={(value, ack) => void mode.choose(value, ack)}
      />
      {mode.error && <p role="alert">{String(mode.error)}</p>}
      <button onClick={() => void mode.refresh()}>刷新权限</button>
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
async function modeReady(name = '自动审核') {
  await waitFor(() =>
    expect(screen.getByRole('button', { name: `执行权限：${name}` }).hasAttribute('disabled')).toBe(
      false,
    ),
  )
}
it('uses the new account full default without saving a preference or opening a confirmation', async () => {
  storedMode = { executionMode: 'full', modeRevision: 1, fullAccessConfirmed: false }
  render(
    <TestWorkspace vault={createVault()}>
      <ModeHarness />
    </TestWorkspace>,
  )
  expect(screen.getByRole('button', { name: '执行权限：自主执行' }).hasAttribute('disabled')).toBe(
    true,
  )
  await modeReady('自主执行')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(updateExecutionMode).not.toHaveBeenCalled()
  choose('逐项确认')
  await modeReady('逐项确认')
})
it('shares saved mode across new/existing conversations, remounts and full page reloads', async () => {
  const vault = createVault()
  const view = (value: Conversation | null) => (
    <TestWorkspace vault={vault}>
      <ModeHarness value={value} />
    </TestWorkspace>
  )
  const mounted = render(view(null))
  await modeReady()
  choose('逐项确认')
  await modeReady('逐项确认')
  expect(updateExecutionMode).toHaveBeenCalledWith(
    { executionMode: 'auto', modeRevision: 1, fullAccessConfirmed: false },
    'ask',
    false,
  )
  expect(vault.getSnapshot()['composer:new']).toBeUndefined()
  mounted.rerender(view(conversation))
  expect(screen.getByRole('button', { name: '执行权限：逐项确认' })).toBeTruthy()
  mounted.rerender(view({ ...conversation, id: 'second', executionMode: 'full' }))
  expect(screen.getByRole('button', { name: '执行权限：逐项确认' })).toBeTruthy()
  expect(fetch).toHaveBeenCalledTimes(1)
  mounted.unmount()
  clearQueryResources() // Refresh must restore the server setting, not a local draft.
  render(view(null))
  await modeReady('逐项确认')
  expect(
    messageSubmission({ text: '创建工作', files: [], key: 'key' }, undefined, undefined, 'ask')
      .body,
  ).toMatchObject({ executionMode: 'ask', newConversation: true })
  expect(
    messageSubmission({ text: '继续', files: [], key: 'next' }, 'second', undefined, 'ask').body,
  ).toMatchObject({ executionMode: 'ask', conversationId: 'second' })
})
it('refreshes account preferences once after another tab changes them, without polling', async () => {
  render(
    <TestWorkspace vault={createVault()}>
      <ModeHarness />
    </TestWorkspace>,
  )
  await modeReady()
  storedMode = { executionMode: 'full', modeRevision: 2, fullAccessConfirmed: true }
  await act(async () => document.dispatchEvent(new Event('visibilitychange')))
  await modeReady('自主执行')
  expect(fetch).toHaveBeenCalledTimes(2)
  act(() => window.dispatchEvent(new Event('focus')))
  expect(fetch).toHaveBeenCalledTimes(2)
})
it('keeps uncertain send retries unchanged even after the account mode changes', () => {
  const pending = {
    key: 'original',
    body: { text: '原消息', attachmentIds: [], replyTo: null, executionMode: 'ask' as const },
  }
  expect(
    messageSubmission(
      { text: '原消息', files: [], key: 'original', pending },
      'first',
      undefined,
      'full',
    ),
  ).toBe(pending)
})
it('rolls back failed account saves and ignores late results after switching accounts', async () => {
  const vault = createVault(),
    request = deferred<ExecutionSettings>()
  vi.mocked(updateExecutionMode)
    .mockRejectedValueOnce(new Error('保存失败'))
    .mockReturnValueOnce(request.promise)
  const view = (account = identity) => (
    <TestWorkspace vault={vault} account={account}>
      <ModeHarness value={conversation} />
    </TestWorkspace>
  )
  const mounted = render(view())
  await modeReady()
  choose('逐项确认')
  await screen.findByRole('alert')
  expect(screen.getByRole('button', { name: '执行权限：自动审核' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '刷新权限' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  choose('逐项确认')
  const other = { ...identity, member: { ...identity.member, id: 'another' } }
  act(() => vault.resume(other))
  mounted.rerender(view(other))
  await act(async () =>
    request.resolve({ executionMode: 'ask', modeRevision: 2, fullAccessConfirmed: false }),
  )
  await modeReady()
  expect(screen.queryByRole('alert')).toBeNull()
})
it('keeps desktop controls accessible and the microphone stable while recording', () => {
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
    retryWait: 0,
    children: null,
    executionControl: <ExecutionModePicker value="auto" acknowledged={false} onChange={vi.fn()} />,
    recording: {
      state: 'idle' as const,
      seconds: 0,
      start: vi.fn(),
      stop: vi.fn(),
      cancel: vi.fn(),
    },
  }
  const view = render(<MessageComposer {...props} />)
  const attach = screen.getByRole('button', { name: '添加附件' })
  const mode = screen.getByRole('button', { name: '执行权限：自动审核' })
  const context = screen.getByRole('button', { name: /^上下文使用情况/ })
  const mic = screen.getByRole('button', { name: '录制语音' })
  expect(screen.getByRole('button', { name: '发送' })).toBeTruthy()
  view.rerender(
    <MessageComposer
      {...props}
      recording={{ ...props.recording, state: 'recording', seconds: 15 }}
    />,
  )
  expect(screen.getByRole('button', { name: '停止录音 · 15 秒' })).toBe(mic)
  expect(screen.getByRole('button', { name: '执行权限：自动审核' })).toBe(mode)
  expect(screen.getByRole('button', { name: /^上下文使用情况/ })).toBe(context)
  expect((attach as HTMLButtonElement).disabled).toBe(true)
  view.rerender(
    <MessageComposer
      {...props}
      executionControl={
        <ExecutionModePicker value="auto" acknowledged={false} disabled onChange={vi.fn()} />
      }
    />,
  )
  expect(screen.getByRole('button', { name: '执行权限：自动审核' })).toBe(mode)
  expect((mode as HTMLButtonElement).disabled).toBe(true)
})

it('preserves pending text, attachment preview and recording controls in the browser composer', () => {
  const { container } = render(
    <MessageComposer
      containerRef={createRef<HTMLDivElement>()}
      send={vi.fn()}
      addFiles={vi.fn()}
      composer={{
        text: '保持原文',
        files: [
          {
            id: 'audio',
            file: new File(['audio'], 'voice.webm', { type: 'audio/webm' }),
            url: 'blob:preview',
          },
        ],
        key: 'draft',
        replyTo: 'source',
      }}
      locked
      change={vi.fn()}
      textInput={createRef<HTMLTextAreaElement>()}
      busy={false}
      previewUploading={false}
      pending
      retryWait={0}
      recording={{
        state: 'recording',
        seconds: 12,
        start: vi.fn(),
        stop: vi.fn(),
        cancel: vi.fn(),
      }}
    >
      <span>附件预览</span>
    </MessageComposer>,
  )
  const input = screen.getByRole('textbox', { name: '工作消息' }) as HTMLTextAreaElement
  expect(input.value).toBe('保持原文')
  expect(input.readOnly).toBe(true)
  expect(screen.getByText('附件预览')).toBeTruthy()
  expect(screen.getByRole('button', { name: '停止录音 · 12 秒' })).toBeTruthy()
  expect(container.querySelector('[data-recording="true"]')).toBeTruthy()
  expect(screen.getByText('12s')).toBeTruthy()
  expect(screen.getByRole('button', { name: '原样重试，确认结果' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '取消补充关联' })).toBeTruthy()
})

function fillAnswers() {
  fireEvent.click(screen.getByLabelText('网站上线'))
  fireEvent.click(screen.getByLabelText('实施计划'))
  fireEvent.change(screen.getByRole('textbox', { name: '何时完成？ · 自由回答' }), {
    target: { value: '下周五' },
  })
}
it('auto-advances single choices, replaces legacy multiple choices and preserves drafts through collapse and remount', () => {
  const vault = createVault(),
    answer = vi.fn(),
    cancel = vi.fn()
  const view = () => (
    <TestWorkspace vault={vault}>
      <QuestionPanel item={question} busy={false} error="" onAnswer={answer} onCancel={cancel} />
    </TestWorkspace>
  )
  const mounted = render(view())
  expect(screen.queryByText('包含哪些内容？')).toBeNull()
  expect(screen.getByRole('button', { name: '上一个' }).hasAttribute('disabled')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '下一个' }))
  expect(answer).not.toHaveBeenCalled()
  expect(screen.getByText(/请回答当前问题/)).toBeTruthy()
  fillAnswers()
  expect(answer).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '上一个' }))
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect((screen.getByLabelText('实施计划') as HTMLInputElement).checked).toBe(true)
  expect((screen.getByLabelText('风险说明') as HTMLInputElement).checked).toBe(false)
  fireEvent.click(screen.getByLabelText('风险说明'))
  expect(screen.getByText('第 3 / 3 题')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '上一个' }))
  expect((screen.getByLabelText('实施计划') as HTMLInputElement).checked).toBe(false)
  expect((screen.getByLabelText('风险说明') as HTMLInputElement).checked).toBe(true)
  fireEvent.click(screen.getByLabelText('风险说明'))
  expect(screen.getByText('第 3 / 3 题')).toBeTruthy()
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
    { questionId: 'scope', optionIds: ['risk'], text: '' },
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
  expect(answer).not.toHaveBeenCalled()
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
    expect(screen.getByRole('button', { name: '下一个' }).hasAttribute('disabled')).toBe(false),
  )
  expect(screen.queryByRole('button', { name: '提交回答' })).toBeNull()
  expect((screen.getByLabelText('网站上线') as HTMLInputElement).checked).toBe(false)
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
