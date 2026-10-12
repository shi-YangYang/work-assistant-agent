// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { usePopover } from '../../../../apps/web/src/components/overlays/usePopover'

function Example({ disabled = false, scopeKey = 'chat' }) {
  const popover = usePopover({ disabled, scopeKey })
  return (
    <>
      <button {...popover.triggerProps} disabled={disabled}>
        打开附件
      </button>
      <div {...popover.panelProps} role="dialog" aria-label="附件">
        <button onClick={() => popover.close()}>选择文件</button>
      </div>
      <button>外部按钮</button>
    </>
  )
}
afterEach(cleanup)

it('hides unsupported popovers initially and supports repeated trigger, selection and outside dismissal', () => {
  expect(HTMLElement.prototype.showPopover).toBeUndefined()
  render(<Example />)
  const trigger = screen.getByRole('button', { name: '打开附件' })
  const panel = document.getElementById(trigger.getAttribute('aria-controls')!)!
  expect(panel.hidden).toBe(true)
  expect(panel.style.display).toBe('none')
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog', { name: '附件' })).toBe(panel)
  fireEvent.click(trigger)
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(trigger)
  fireEvent.click(screen.getByRole('button', { name: '选择文件' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  fireEvent.click(trigger)
  fireEvent.pointerDown(screen.getByRole('button', { name: '外部按钮' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('closes on Escape or focus leaving, and restores focus only on explicit dismissal', () => {
  render(<Example />)
  const trigger = screen.getByRole('button', { name: '打开附件' })
  fireEvent.click(trigger)
  screen.getByRole('button', { name: '选择文件' }).focus()
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  fireEvent.click(trigger)
  fireEvent.focusIn(screen.getByRole('button', { name: '外部按钮' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('does not reopen when a navigation drawer closes and reopens, or controls become enabled again', () => {
  const view = render(<Example />)
  const trigger = screen.getByRole('button', { name: '打开附件' })
  fireEvent.click(trigger)
  view.rerender(<Example disabled />)
  view.rerender(<Example />)
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(trigger)
  view.rerender(<Example scopeKey="other" />)
  view.rerender(<Example />)
  expect(screen.queryByRole('dialog')).toBeNull()
})
