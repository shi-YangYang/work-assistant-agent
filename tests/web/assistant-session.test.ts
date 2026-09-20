import type { KeyboardEvent } from 'react'
import { expect, it, vi } from 'vitest'
import { ApiError } from '../../apps/web/src/api/client'
import { resumeConversation } from '../../apps/web/src/features/assistant/api/restore-conversation'
import { exampleText, submitOnEnter } from '../../apps/web/src/features/assistant/utils/session'

it('restores a remembered conversation even outside the first list page, using reads only', async () => {
  const paths: string[] = []
  const id = await resumeConversation('older', async <T>(path: string) => {
    paths.push(path)
    return { id: 'older' } as T
  })
  expect(id).toBe('older')
  expect(paths).toEqual(['/conversations/older'])
})

it.each([403, 404])(
  'falls back to an accessible conversation after stale access (%s)',
  async (status) => {
    const paths: string[] = []
    const id = await resumeConversation('deleted', async <T>(path: string) => {
      paths.push(path)
      if (path.endsWith('/deleted')) throw new ApiError(status, 'missing', '会话不可用')
      return { items: [{ id: 'latest' }] } as T
    })
    expect(id).toBe('latest')
    expect(paths).toEqual(['/conversations/deleted', '/conversations'])
  },
)

it('leaves a genuinely empty account blank without creating a conversation or hiding outages', async () => {
  expect(await resumeConversation(null, async <T>() => ({ items: [] }) as T)).toBeNull()
  let calls = 0
  const read = async <T>(): Promise<T> => {
    calls++
    throw new ApiError(503, 'offline', '连接失败')
  }
  await expect(resumeConversation('remembered', read)).rejects.toThrow('连接失败')
  expect(calls).toBe(1)
})

it('Enter sends once; Shift+Enter and IME confirmation keep editing', () => {
  const send = vi.fn()
  const preventDefault = vi.fn()
  const event = {
    key: 'Enter',
    shiftKey: false,
    repeat: false,
    nativeEvent: { isComposing: false, keyCode: 13 },
    preventDefault,
  } as unknown as KeyboardEvent<HTMLTextAreaElement>
  submitOnEnter(event, send)
  expect(send).toHaveBeenCalledTimes(1)
  expect(preventDefault).toHaveBeenCalledTimes(1)
  for (const patch of [
    { shiftKey: true },
    { nativeEvent: { isComposing: true, keyCode: 13 } },
    { nativeEvent: { isComposing: false, keyCode: 229 } },
    { key: 'a' },
  ])
    submitOnEnter({ ...event, ...patch } as KeyboardEvent<HTMLTextAreaElement>, send)
  expect(send).toHaveBeenCalledTimes(1)
  expect(preventDefault).toHaveBeenCalledTimes(1)
  submitOnEnter({ ...event, repeat: true }, send)
  expect(send).toHaveBeenCalledTimes(1)
  expect(preventDefault).toHaveBeenCalledTimes(2)
})

it('examples only fill a blank composer and never overwrite existing input', () => {
  expect(exampleText('', '记录今天的工作：')).toBe('记录今天的工作：')
  expect(exampleText('我刚写的内容', '查看我的工作')).toBe('我刚写的内容')
})
