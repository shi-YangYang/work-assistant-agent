import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, expect, it, vi } from 'vitest'
import { useMessageSubmission } from '../../apps/web/src/features/assistant/hooks/useMessageSubmission'

const mocks = vi.hoisted(() => ({
  send: vi.fn(),
  setDraft: vi.fn(),
  remember: vi.fn(),
}))
vi.mock('@web/features/assistant/api/requests', () => ({
  sendMessage: mocks.send,
  uploadAttachment: vi.fn(),
}))
vi.mock('@web/lib/workspace', () => ({
  useWorkspace: () => ({ setDraft: mocks.setDraft, rememberConversation: mocks.remember }),
}))

beforeEach(() => vi.clearAllMocks())

it('remembers the accepted conversation when navigating away during submission', async () => {
  let resolve!: (value: { conversationId: string }) => void
  mocks.send.mockReturnValue(new Promise((done) => (resolve = done)))
  const active = { current: true }
  const onSent = vi.fn()
  const refresh = vi.fn()
  let submission!: ReturnType<typeof useMessageSubmission>
  function Harness() {
    submission = useMessageSubmission({
      composer: { text: '发送后切换页面', files: [], key: 'draft-key' },
      composerKey: 'new-conversation',
      personaId: 'dabao',
      onSent,
      previewUploading: false,
      capturing: false,
      active,
      setLimitError: vi.fn(),
      setSendError: vi.fn(),
      retryWait: 0,
      refresh,
    })
    return null
  }
  renderToStaticMarkup(createElement(Harness))
  const pending = submission.send()
  active.current = false
  resolve({ conversationId: 'accepted-conversation' })
  await pending
  expect(mocks.remember).toHaveBeenCalledExactlyOnceWith('accepted-conversation')
  expect(onSent).not.toHaveBeenCalled()
  expect(refresh).not.toHaveBeenCalled()
})
