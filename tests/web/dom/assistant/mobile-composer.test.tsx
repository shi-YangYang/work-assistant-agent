// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useRef, useState, type ComponentProps } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MessageComposer } from '../../../../apps/web/src/features/assistant/components/composer/MessageComposer'
import { ReasoningEffortPicker } from '../../../../apps/web/src/features/assistant/components/composer/controls/ReasoningEffortPicker'
import { ExecutionModePicker } from '../../../../apps/web/src/features/assistant/components/composer/controls/ExecutionModePicker'
import type { Composer } from '../../../../apps/web/src/features/assistant/lib/audio-capture'

type Props = ComponentProps<typeof MessageComposer>
const send = vi.fn(async () => {})
const addFiles = vi.fn(async () => {})
const chooseReasoning = vi.fn()
const chooseExecution = vi.fn()
const chooseWork = vi.fn()
const start = vi.fn(async () => true)
const stop = vi.fn()
const cancel = vi.fn()
function Harness({
  text = '',
  scope = 'first',
  ...overrides
}: Partial<Props> & { text?: string; scope?: string }) {
  const [composer, change] = useState<Composer>({
    text,
    key: 'original',
    files: [],
    replyTo: 'reply',
  })
  return (
    <MessageComposer
      containerRef={useRef(null)}
      textInput={useRef(null)}
      composer={composer}
      change={change}
      send={send}
      addFiles={addFiles}
      locked={false}
      busy={false}
      previewUploading={false}
      pending={false}
      retryWait={0}
      contextKey={scope}
      recording={{ state: 'idle', seconds: 0, start, stop, cancel }}
      workReference={{
        setPickerOpen: chooseWork,
        pickerOpen: false,
        loading: false,
        error: undefined,
        retry: vi.fn(),
        remove: vi.fn(),
        select: vi.fn(),
      }}
      reasoningControl={
        <ReasoningEffortPicker
          options={[{ effort: 'low' }, { effort: 'high' }]}
          selected={{ effort: 'high' }}
          saving={false}
          onChange={chooseReasoning}
        />
      }
      executionControl={
        <ExecutionModePicker value="ask" acknowledged={false} onChange={chooseExecution} />
      }
      {...overrides}
    >
      {null}
    </MessageComposer>
  )
}
const more = () => screen.getByRole('button', { name: '更多功能' })
const panel = () => screen.getByRole('region', { name: '更多功能' })
beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
  vi.stubGlobal('innerWidth', 390)
  vi.stubGlobal('innerHeight', 844)
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

it('starts compact, shows named tools with current values and switches focus without losing a draft', () => {
  render(<Harness />)
  const input = screen.getByRole<HTMLTextAreaElement>('textbox')
  const voice = screen.getByRole('button', { name: '录制语音' })
  expect(screen.queryByRole('button', { name: '发送' })).toBeNull()
  expect(screen.queryByRole('region')).toBeNull()
  expect(screen.queryByRole('button', { name: /思考强度/ })).toBeNull()
  fireEvent.change(input, { target: { value: '新草稿' } })
  expect(screen.getByRole('button', { name: '发送' })).toBeTruthy()
  act(() => input.focus())
  fireEvent.click(more())
  expect(document.activeElement).not.toBe(input)
  expect(more().getAttribute('aria-expanded')).toBe('true')
  for (const name of [
    '添加图片',
    '添加文件',
    '引用工作',
    '上下文使用情况：尚未计算',
    '思考强度：high',
    '执行权限：逐项确认',
  ])
    expect(within(panel()).getByRole('button', { name })).toBeTruthy()
  act(() => input.focus())
  expect(screen.queryByRole('region')).toBeNull()
  expect(document.activeElement).toBe(input)
  expect(input.value).toBe('新草稿')
  expect(screen.getByRole('button', { name: '录制语音' })).toBe(voice)
  expect(send).not.toHaveBeenCalled()
})

it('keeps stop, blocked recovery and uncertain retry visible even with an empty draft', () => {
  const interrupt = vi.fn()
  const view = render(<Harness task={{ running: true, interrupt } as unknown as Props['task']} />)
  fireEvent.click(screen.getByRole('button', { name: '中断' }))
  expect(interrupt).toHaveBeenCalledOnce()
  view.rerender(<Harness pending />)
  expect(screen.getByRole('button', { name: '原样重试，确认结果' })).toBeTruthy()
  view.rerender(<Harness task={{ blocked: true } as Props['task']} />)
  expect(screen.getByRole<HTMLButtonElement>('button', { name: '正在恢复处理状态' }).disabled).toBe(
    true,
  )
  expect(send).not.toHaveBeenCalled()
})

it('keeps context reachable while locked without enabling attachments or restricted settings', () => {
  const view = render(
    <Harness
      locked
      pending
      reasoningControl={
        <ReasoningEffortPicker
          options={[{ effort: 'high' }]}
          selected={{ effort: 'high' }}
          saving={false}
          disabled
          onChange={chooseReasoning}
        />
      }
      executionControl={
        <ExecutionModePicker value="ask" acknowledged={false} disabled onChange={chooseExecution} />
      }
    />,
  )
  fireEvent.click(more())
  for (const name of ['添加图片', '添加文件', '引用工作', '思考强度：high', '执行权限：逐项确认']) {
    const control = within(panel()).getByRole<HTMLButtonElement>('button', { name })
    expect(control.disabled).toBe(true)
    fireEvent.click(control)
  }
  expect(screen.queryByRole('menu')).toBeNull()
  expect(chooseWork).not.toHaveBeenCalled()
  expect(chooseReasoning).not.toHaveBeenCalled()
  expect(chooseExecution).not.toHaveBeenCalled()
  expect(addFiles).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: /上下文使用情况/ }))
  expect(within(screen.getByRole('dialog')).getByText('助手开始处理消息后显示用量。')).toBeTruthy()

  view.rerender(<Harness locked previewUploading />)
  fireEvent.click(screen.getByRole('button', { name: '思考强度：high' }))
  expect(screen.getByRole('menu', { name: '思考强度' })).toBeTruthy()
  view.rerender(
    <Harness locked recording={{ state: 'recording', seconds: 1, start, stop, cancel }} />,
  )
  expect(screen.queryByRole('region')).toBeNull()
  expect(screen.queryByRole('menu')).toBeNull()
  expect(more().getAttribute('disabled')).not.toBeNull()
  view.rerender(<Harness locked />)
  act(() => {
    window.innerWidth = 1280
    window.dispatchEvent(new Event('resize'))
  })
  expect(screen.getByRole<HTMLButtonElement>('button', { name: '添加附件' }).disabled).toBe(true)
})

it('opens a single detail at a time, closes the top layer first with Escape and preserves full permission confirmation', () => {
  render(<Harness />)
  fireEvent.click(more())
  fireEvent.click(screen.getByRole('button', { name: /上下文使用情况/ }))
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(panel()).toBeTruthy()
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('region')).toBeNull()
  fireEvent.click(more())
  fireEvent.click(screen.getByRole('button', { name: '思考强度：high' }))
  expect(screen.getByRole('menu', { name: '思考强度' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '执行权限：逐项确认' }))
  expect(screen.queryByRole('menu', { name: '思考强度' })).toBeNull()
  fireEvent.click(screen.getByRole('menuitemradio', { name: /自主执行/ }))
  expect(screen.getByRole('dialog', { name: '开启自主执行' })).toBeTruthy()
  expect(chooseExecution).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  fireEvent.keyDown(more(), { key: 'Escape' })
  expect(screen.queryByRole('region')).toBeNull()
  expect(document.activeElement).toBe(more())
})

it('keeps composition input and composition Escape from submitting or closing the panel', () => {
  render(<Harness text="输入法草稿" />)
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', isComposing: true })
  expect(send).not.toHaveBeenCalled()
  fireEvent.click(more())
  fireEvent.keyDown(more(), { key: 'Escape', isComposing: true })
  expect(panel()).toBeTruthy()
  fireEvent.pointerDown(document.body)
  expect(screen.queryByRole('region')).toBeNull()
})

it('closes before system pickers and preserves text on cancellation or work selection', () => {
  const fileClick = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {})
  const view = render(<Harness text="带附件的草稿" />)
  fireEvent.click(more())
  fireEvent.click(within(panel()).getByRole('button', { name: '添加图片' }))
  expect(screen.queryByRole('region')).toBeNull()
  expect(fileClick).toHaveBeenCalledOnce()
  expect(screen.getByRole<HTMLTextAreaElement>('textbox').value).toBe('带附件的草稿')
  const file = new File(['image'], 'photo.png', { type: 'image/png' })
  fireEvent.change(view.container.querySelector('input[type="file"]')!, {
    target: { files: [file] },
  })
  expect(addFiles).toHaveBeenCalledWith([file])
  fireEvent.click(more())
  fireEvent.click(within(panel()).getByRole('button', { name: '引用工作' }))
  expect(chooseWork).toHaveBeenCalledWith(true)
  expect(screen.queryByRole('region')).toBeNull()
  expect(send).not.toHaveBeenCalled()
})

it('closes all layers on a conversation or breakpoint change without remounting input and recording controls', () => {
  const view = render(<Harness text="草稿" />)
  const input = screen.getByRole('textbox')
  const voice = screen.getByRole('button', { name: '录制语音' })
  fireEvent.click(more())
  fireEvent.click(screen.getByRole('button', { name: '思考强度：high' }))
  view.rerender(<Harness text="草稿" scope="second" />)
  expect(screen.queryByRole('region')).toBeNull()
  expect(screen.queryByRole('menu')).toBeNull()
  fireEvent.click(more())
  act(() => {
    window.innerWidth = 1280
    window.dispatchEvent(new Event('resize'))
  })
  expect(screen.queryByRole('region')).toBeNull()
  expect(screen.getByRole('button', { name: '添加附件' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '思考强度：high' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '添加图片' })).toBeNull()
  expect(screen.getByRole('textbox')).toBe(input)
  expect(screen.getByRole('button', { name: '录制语音' })).toBe(voice)
})

it('caps multiline input and removes only the mobile height when returning to desktop', () => {
  render(<Harness />)
  const input = screen.getByRole<HTMLTextAreaElement>('textbox')
  Object.defineProperty(input, 'scrollHeight', { configurable: true, value: 350 })
  fireEvent.change(input, { target: { value: '一\n二\n三\n四\n五' } })
  expect(input.style.height).toBe('112px')
  Object.defineProperty(input, 'scrollHeight', { configurable: true, value: 24 })
  fireEvent.change(input, { target: { value: '' } })
  expect(input.style.height).toBe('44px')
  act(() => {
    window.innerWidth = 1280
    window.dispatchEvent(new Event('resize'))
  })
  expect(input.style.height).toBe('')
})

it('closes the panel when tap recording starts and keeps capture controls visible while locked', () => {
  const view = render(<Harness />)
  fireEvent.click(more())
  fireEvent.click(screen.getByRole('button', { name: '录制语音' }))
  expect(start).toHaveBeenCalledOnce()
  expect(screen.queryByRole('region')).toBeNull()
  view.rerender(
    <Harness locked recording={{ state: 'recording', seconds: 12, start, stop, cancel }} />,
  )
  expect(more().getAttribute('disabled')).not.toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '停止录音 · 12 秒' }))
  expect(stop).toHaveBeenCalledWith()
})

it('does not hide context failures or recovery status in a closed panel', () => {
  render(<Harness contextUnavailable />)
  expect(screen.getByRole('status').textContent).toBe('暂不可用')
  expect(screen.queryByRole('region')).toBeNull()
})

it('preserves a held recording across panel closing and sends only once on release', async () => {
  vi.useFakeTimers()
  vi.stubGlobal(
    'PointerEvent',
    class extends MouseEvent {
      pointerId: number
      isPrimary: boolean
      constructor(type: string, options: PointerEventInit = {}) {
        super(type, options)
        this.pointerId = options.pointerId ?? 1
        this.isPrimary = options.isPrimary ?? true
      }
    },
  )
  render(<Harness />)
  fireEvent.click(more())
  const voice = screen.getByRole('button', { name: '录制语音' })
  const pointer = { pointerId: 1, button: 0, clientY: 500, clientX: 30, isPrimary: true }
  fireEvent.pointerDown(voice, pointer)
  await act(async () => {
    await vi.advanceTimersByTimeAsync(350)
  })
  expect(screen.queryByRole('region')).toBeNull()
  expect(start).toHaveBeenCalledOnce()
  expect(cancel).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '录制语音' })).toBe(voice)
  fireEvent.pointerUp(voice, pointer)
  fireEvent.click(voice, { detail: 1 })
  expect(stop).toHaveBeenCalledExactlyOnceWith(true)
  expect(start).toHaveBeenCalledOnce()
  expect(send).not.toHaveBeenCalled()
})
