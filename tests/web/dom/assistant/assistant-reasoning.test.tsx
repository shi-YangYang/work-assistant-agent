// @vitest-environment jsdom
import type { ReasoningSettings } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ReasoningEffortPicker } from '../../../../apps/web/src/features/assistant/components/composer/controls/ReasoningEffortPicker'
import { MessageComposer } from '../../../../apps/web/src/features/assistant/components/composer/MessageComposer'
import { useReasoningEffort } from '../../../../apps/web/src/features/assistant/hooks/preferences/useReasoningEffort'
import { useMessageSubmission } from '../../../../apps/web/src/features/assistant/hooks/composer/useMessageSubmission'
import { useWorkspace } from '../../../../apps/web/src/lib/workspace'
import { assistantQuery } from '../../../../apps/web/src/features/assistant/api/queries'
import { clearQueryResources } from '../../../../apps/web/src/lib/query-resource'
import type { Composer } from '../../../../apps/web/src/features/assistant/lib/audio-capture'
import { createVault, deferred, identity, TestWorkspace } from '../helpers'

const options = [{ effort: 'low' }, { effort: 'high' }, { effort: 'max' }]
const initial: ReasoningSettings = {
  options,
  selected: options[1],
  preferenceRevision: 0,
  configVersion: 'config-1',
}
let stored: ReasoningSettings
let saveResponse: Promise<Response> | undefined
let uploadResponse: Promise<Response> | undefined
let sentResponse: Response | undefined
let error = ''
let controller: ReturnType<typeof useReasoningEffort>
let send: () => Promise<void>
const vault = () => {
  const result = createVault()
  result.writer()('draft', { text: '保留的草稿', key: 'draft-key', files: [] })
  return result
}
function Harness({ running = false }: { running?: boolean }) {
  controller = useReasoningEffort()
  const { drafts, setDraft } = useWorkspace()
  const composer = (drafts.draft as Composer) ?? { text: '', key: '', files: [] }
  const active = useRef(true)
  const submission = useMessageSubmission({
    composer,
    composerKey: 'draft',
    personaId: 'professional',
    reasoning: controller,
    onSent: vi.fn(),
    previewUploading: false,
    capturing: false,
    active,
    setLimitError: vi.fn(),
    setSendError: (e) => {
      error = String(e)
    },
    retryWait: 0,
    refresh: vi.fn(),
  })
  send = submission.send
  return (
    <>
      <output>{String(controller.error)}</output>
      <MessageComposer
        containerRef={useRef(null)}
        textInput={useRef(null)}
        composer={composer}
        change={(next) => setDraft('draft', next)}
        send={send}
        addFiles={async () => {}}
        locked={false}
        busy={submission.busy}
        previewUploading={false}
        pending={!!composer.pending}
        retryWait={0}
        recording={{
          state: 'idle',
          seconds: 0,
          start: async () => {},
          stop: vi.fn(),
          cancel: vi.fn(),
        }}
        reasoningSaving={!controller.ready}
        reasoningControl={
          <ReasoningEffortPicker
            options={controller.options}
            selected={controller.selected}
            saving={controller.saving}
            onChange={(id) => void controller.choose(id)}
          />
        }
        task={
          running ? ({ running: true, cancelling: false, interrupt: vi.fn() } as never) : undefined
        }
      >
        {null}
      </MessageComposer>
    </>
  )
}
beforeEach(() => {
  stored = structuredClone(initial)
  saveResponse = undefined
  uploadResponse = undefined
  sentResponse = undefined
  error = ''
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith('/uploads')) return uploadResponse!
      if (String(url).endsWith('/messages'))
        return (
          sentResponse ??
          new Response(JSON.stringify({ conversationId: 'chat', messageId: 'm', jobId: 'j' }))
        )
      if (init?.method === 'PATCH') {
        if (saveResponse) return saveResponse
        const body = JSON.parse(String(init.body))
        stored = {
          ...stored,
          selected: options.find((option) => option.effort === body.effort)!,
          preferenceRevision: stored.preferenceRevision + 1,
        }
      }
      return new Response(JSON.stringify(stored))
    }),
  )
})
afterEach(() => {
  cleanup()
  clearQueryResources()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
const patches = () => vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'PATCH')
const posts = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/messages'))

it('keeps toolbar order and mounted controls while selecting the next message during a running task', async () => {
  render(
    <TestWorkspace vault={vault()}>
      <Harness running />
    </TestWorkspace>,
  )
  const high = await screen.findByRole('button', { name: '思考强度：high' })
  const context = screen.getByRole('button', { name: /上下文使用情况/ })
  const microphone = screen.getByRole('button', { name: '录制语音' })
  const stop = screen.getByRole('button', { name: '中断' })
  expect([...high.parentElement!.children]).toEqual([context, high, microphone, stop])
  fireEvent.keyDown(high, { key: 'ArrowDown' })
  const selected = screen.getByRole('menuitemradio', { name: 'high' })
  expect(document.activeElement).toBe(selected)
  fireEvent.keyDown(selected, { key: 'End' })
  expect(document.activeElement).toBe(screen.getByRole('menuitemradio', { name: 'max' }))
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(document.activeElement).toBe(high)
  fireEvent.click(high)
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'low' }))
  await screen.findByRole('button', { name: '思考强度：low' })
  expect(screen.getByRole('button', { name: '录制语音' })).toBe(microphone)
  expect(screen.getByRole('button', { name: '中断' })).toBe(stop)
  expect(posts()).toHaveLength(0)
})

it('serializes rapid selection, blocks sending until saved and includes the committed reference', async () => {
  const pending = deferred<Response>()
  saveResponse = pending.promise
  render(
    <TestWorkspace vault={vault()}>
      <Harness />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：high' })
  let saving!: Promise<void>
  act(() => {
    saving = controller.choose('low')
    void controller.choose('max')
  })
  await act(() => send())
  expect(patches()).toHaveLength(1)
  expect(posts()).toHaveLength(0)
  expect(screen.getByRole('button', { name: '思考强度：high' }).getAttribute('aria-busy')).toBe(
    'true',
  )
  await act(async () => {
    pending.resolve(
      new Response(JSON.stringify({ ...initial, selected: options[0], preferenceRevision: 1 })),
    )
    await saving
  })
  await act(() => send())
  expect(JSON.parse(String(posts()[0][1]?.body)).reasoning).toEqual({
    effort: 'low',
    preferenceRevision: 1,
    configVersion: 'config-1',
  })
})

it('keeps an uploaded draft when another conversation starts saving and sends only after an explicit retry', async () => {
  const upload = deferred<Response>()
  const save = deferred<Response>()
  uploadResponse = upload.promise
  saveResponse = save.promise
  vi.stubGlobal(
    'URL',
    class extends URL {
      static revokeObjectURL = vi.fn()
    },
  )
  const currentVault = vault()
  currentVault.writer()('draft', {
    text: '保留的草稿',
    key: 'draft-key',
    files: [
      {
        id: 'file',
        file: new File(['data'], 'data.txt', { type: 'text/plain' }),
        url: 'blob:file',
      },
    ],
  })
  let otherConversation!: ReturnType<typeof useReasoningEffort>
  function OtherConversation() {
    otherConversation = useReasoningEffort()
    return null
  }
  render(
    <TestWorkspace vault={currentVault}>
      <Harness />
      <OtherConversation />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：high' })
  let sending!: Promise<void>
  act(() => {
    sending = send()
  })
  await waitFor(() =>
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/uploads')),
    ).toHaveLength(1),
  )
  let saving!: Promise<void>
  act(() => {
    saving = otherConversation.choose('low')
  })
  await act(async () => {
    upload.resolve(new Response(JSON.stringify({ id: 'attachment', kind: 'document' })))
    await sending
  })
  expect(posts()).toHaveLength(0)
  const draft = currentVault.getSnapshot().draft as Composer
  expect(draft.text).toBe('保留的草稿')
  expect(draft.pending).toBeUndefined()
  expect(draft.files[0].attachment?.id).toBe('attachment')
  expect(draft.files[0].failed).toBe(false)
  expect(draft.sending).toBe(false)
  expect(draft.uploading).toBeUndefined()
  await act(async () => {
    save.resolve(
      new Response(JSON.stringify({ ...initial, selected: options[0], preferenceRevision: 1 })),
    )
    await saving
  })
  expect(posts()).toHaveLength(0)
  await act(() => send())
  expect(posts()).toHaveLength(1)
  expect(JSON.parse(String(posts()[0][1]?.body))).toMatchObject({
    text: '保留的草稿',
    attachmentIds: ['attachment'],
    reasoning: { effort: 'low', preferenceRevision: 1, configVersion: 'config-1' },
  })
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/uploads')),
  ).toHaveLength(1)
})

it('replays an uncertain pending request with its original reasoning reference and idempotency key', async () => {
  sentResponse = new Response(JSON.stringify({ error: { message: '响应中断', code: 'failed' } }), {
    status: 500,
  })
  const currentVault = vault()
  render(
    <TestWorkspace vault={currentVault}>
      <Harness />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：high' })
  await act(() => send())
  const first = posts()[0][1]!
  expect((currentVault.getSnapshot().draft as Composer).pending?.body.reasoning?.effort).toBe(
    'high',
  )
  await act(() => controller.choose('low'))
  expect(controller.reference()?.effort).toBe('low')
  sentResponse = undefined
  await act(() => send())
  expect(posts()).toHaveLength(2)
  expect(posts()[1][1]?.body).toBe(first.body)
  expect(posts()[1][1]?.headers).toEqual(first.headers)
  expect(currentVault.getSnapshot().draft).toBeUndefined()
})

it('retains draft and effective choice on save failure; synchronizes a conflict once without a message POST', async () => {
  saveResponse = Promise.resolve(
    new Response(JSON.stringify({ error: { message: '保存失败', code: 'failed' } }), {
      status: 500,
    }),
  )
  render(
    <TestWorkspace vault={vault()}>
      <Harness />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：high' })
  await act(() => controller.choose('low'))
  expect(screen.getByRole('textbox', { name: '工作消息' }).getAttribute('aria-label')).toBe(
    '工作消息',
  )
  expect((screen.getByRole('textbox', { name: '工作消息' }) as HTMLTextAreaElement).value).toBe(
    '保留的草稿',
  )
  expect(screen.getByRole('button', { name: '思考强度：high' })).toBeTruthy()
  stored = { ...initial, selected: options[2], configVersion: 'config-2' }
  saveResponse = Promise.resolve(
    new Response(
      JSON.stringify({ error: { message: '设置已变化', code: 'reasoning_settings_changed' } }),
      {
        status: 409,
      },
    ),
  )
  await act(() => controller.choose('low'))
  await screen.findByRole('button', { name: '思考强度：max' })
  expect(
    vi.mocked(fetch).mock.calls.filter(([, init]) => !init?.method || init.method === 'GET'),
  ).toHaveLength(2)
  expect(posts()).toHaveLength(0)
})

it('resynchronizes stale sends once, clears rejected pending request and keeps its draft', async () => {
  const currentVault = vault()
  render(
    <TestWorkspace vault={currentVault}>
      <Harness />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：high' })
  stored = { ...initial, selected: options[0], configVersion: 'config-2' }
  sentResponse = new Response(
    JSON.stringify({ error: { message: '设置已变化', code: 'reasoning_settings_changed' } }),
    { status: 409 },
  )
  await act(() => send())
  await screen.findByRole('button', { name: '思考强度：low' })
  expect(posts()).toHaveLength(1)
  const draft = currentVault.getSnapshot().draft as Composer
  expect(draft.text).toBe('保留的草稿')
  expect(draft.pending).toBeUndefined()
  expect(error).toContain('设置已变化')
})

it('shares saved preferences across conversations and isolates another identity without polling', async () => {
  const first = render(
    <TestWorkspace vault={vault()}>
      <Harness />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：high' })
  await act(() => controller.choose('low'))
  first.unmount()
  const second = render(
    <TestWorkspace vault={vault()}>
      <Harness />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：low' })
  expect(
    vi.mocked(fetch).mock.calls.filter(([, init]) => !init?.method || init.method === 'GET'),
  ).toHaveLength(1)
  second.unmount()
  stored = structuredClone(initial)
  const account = { ...identity, member: { ...identity.member, id: 'other' } }
  render(
    <TestWorkspace vault={createVault(account)} account={account}>
      <Harness />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：high' })
  const count = vi.mocked(fetch).mock.calls.length
  await act(async () => {
    window.dispatchEvent(new Event('focus'))
  })
  expect(vi.mocked(fetch).mock.calls).toHaveLength(count)
})

it('hides the picker when no effort is exposed and still permits normal messaging', async () => {
  stored = { ...initial, options: [], selected: null }
  render(
    <TestWorkspace vault={vault()}>
      <Harness />
    </TestWorkspace>,
  )
  await waitFor(() => expect(controller.ready).toBe(true))
  expect(screen.queryByRole('button', { name: /思考强度/ })).toBeNull()
  await act(() => send())
  expect(JSON.parse(String(posts()[0][1]?.body)).reasoning.effort).toBeNull()
})

it('persists an explicit choice of the initial effort and does not overwrite a newer shared read', async () => {
  const pending = deferred<Response>()
  saveResponse = pending.promise
  render(
    <TestWorkspace vault={vault()}>
      <Harness />
    </TestWorkspace>,
  )
  await screen.findByRole('button', { name: '思考强度：high' })
  let saving!: Promise<void>
  act(() => {
    saving = controller.choose('high')
  })
  await waitFor(() => expect(patches()).toHaveLength(1))
  act(() =>
    assistantQuery<ReasoningSettings>(
      '/assistant/reasoning-settings',
      'company:owner:employee',
    )!.set({ ...initial, selected: options[0], preferenceRevision: 2 }),
  )
  await act(async () => {
    pending.resolve(new Response(JSON.stringify({ ...initial, preferenceRevision: 1 })))
    await saving
  })
  expect(screen.getByRole('button', { name: '思考强度：low' })).toBeTruthy()
  expect(controller.reference()?.preferenceRevision).toBe(2)
})
