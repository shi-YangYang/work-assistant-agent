// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AutoTextarea } from '../../../../apps/web/src/components/forms/AutoTextarea'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('preserves rows while a dialog is hidden and resizes after it becomes visible', () => {
  let visible = false
  let contentHeight = 90
  let resized = () => {}
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(
    () => (visible ? [{}] : []) as unknown as DOMRectList,
  )
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() =>
    visible ? 300 : 0,
  )
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(() =>
    visible ? contentHeight : 0,
  )
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    callback(0)
    return 1
  })
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: () => void) {
        resized = callback
      }
      observe() {}
      disconnect() {}
    },
  )
  const view = render(
    <AutoTextarea
      aria-label="进展"
      defaultValue="已有进展"
      rows={3}
      style={{ borderWidth: '1px', maxHeight: '280px' }}
    />,
  )
  const textarea = screen.getByRole('textbox', { name: '进展' }) as HTMLTextAreaElement
  expect(textarea.style.height).toBe('')
  act(() => {
    visible = true
    resized()
  })
  expect(textarea.style.height).toBe('92px')
  expect(textarea.style.overflowY).toBe('hidden')
  contentHeight = 400
  view.rerender(
    <AutoTextarea
      aria-label="进展"
      defaultValue="更长的进展"
      rows={3}
      style={{ borderWidth: '1px', maxHeight: '280px' }}
    />,
  )
  expect(textarea.style.height).toBe('280px')
  expect(textarea.style.overflowY).toBe('auto')
})
