// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useRef, useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { setCsrf } from '../../../../apps/web/src/api/client'
import { ErrorNotice } from '../../../../apps/web/src/components/feedback/ErrorNotice'
import { useMessageSubmission } from '../../../../apps/web/src/features/assistant/hooks/composer/useMessageSubmission'
import type { Composer } from '../../../../apps/web/src/features/assistant/lib/audio-capture'
import { useWorkspace } from '../../../../apps/web/src/lib/workspace'
import { createVault, TestWorkspace } from '../helpers'

function Harness() {
  const { drafts } = useWorkspace()
  const composer = drafts['composer:first'] as Composer
  const [error, setError] = useState<Error | string>('')
  const active = useRef(true)
  const submission = useMessageSubmission({
    composer,
    composerKey: 'composer:first',
    conversationId: 'conversation',
    personaId: 'professional',
    onSent: vi.fn(),
    previewUploading: false,
    capturing: false,
    active,
    setSendError: setError,
    setLimitError: setError,
    retryWait: 0,
    refresh: vi.fn(),
  })
  return (
    <>
      <button disabled={submission.busy} onClick={() => void submission.send()}>
        发送
      </button>
      <ErrorNotice>{error}</ErrorNotice>
    </>
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it.each([
  [404, 'attachment_unavailable', '附件已不可用，请移除后重新添加。'],
  [404, 'not_found', '记录不存在或无权查看'],
  [503, 'unavailable', '服务暂时不可用，请稍后重试。'],
] as const)('presents %s/%s without automatic upload or resend', async (status, code, message) => {
  setCsrf('test-token')
  const fetch = vi.fn(
    async () =>
      new Response(JSON.stringify({ error: { code, message } }), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
  vi.stubGlobal('fetch', fetch)
  const vault = createVault()
  const composer: Composer = {
    key: 'submission-key',
    text: '保留正文',
    files: [
      {
        id: 'original',
        file: new File(['source'], 'source.py'),
        url: 'blob:original',
        attachment: {
          id: 'server-id',
          kind: 'document',
          name: 'source.py',
          mime: 'text/plain',
          size: 6,
          duration: null,
          url: '/source',
        },
      },
    ],
  }
  vault.writer()('composer:first', composer)
  render(
    <TestWorkspace vault={vault}>
      <Harness />
    </TestWorkspace>,
  )
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
  expect((await screen.findByRole('alert')).textContent).toBe(message)
  await waitFor(() =>
    expect((vault.getSnapshot()['composer:first'] as Composer).sending).toBe(false),
  )
  const restored = vault.getSnapshot()['composer:first'] as Composer
  expect(restored.text).toBe(composer.text)
  expect(restored.files).toEqual(composer.files)
  if (status === 503)
    expect(restored.pending).toMatchObject({
      key: composer.key,
      body: { attachmentIds: ['server-id'] },
    })
  else expect(restored.pending).toBeUndefined()
  expect(fetch).toHaveBeenCalledOnce()
  expect(fetch).toHaveBeenCalledWith(
    '/api/v1/messages',
    expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('server-id'),
    }),
  )
})
