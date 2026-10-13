// @vitest-environment jsdom
import { StrictMode, useState } from 'react'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ConfirmDialog } from '../../../../apps/web/src/components/overlays/ConfirmDialog'
import { dialogs } from '../helpers'

beforeEach(dialogs)
afterEach(cleanup)

it.each(['cancel', 'escape', 'backdrop', 'close'])(
  'dismisses via %s without confirming and restores focus',
  (method) => {
    const confirm = vi.fn()
    function Example() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button onClick={() => setOpen(true)}>打开确认</button>
          {open && (
            <ConfirmDialog title="确认操作" onClose={() => setOpen(false)} onConfirm={confirm}>
              操作说明
            </ConfirmDialog>
          )}
        </>
      )
    }
    render(
      <StrictMode>
        <Example />
      </StrictMode>,
    )
    const trigger = screen.getByRole('button', { name: '打开确认' })
    trigger.focus()
    fireEvent.click(trigger)
    const dialog = screen.getByRole('dialog', { name: '确认操作' })
    const cancel = within(dialog).getByRole('button', { name: '取消' })
    expect(document.activeElement).toBe(cancel)
    expect(document.getElementById(dialog.getAttribute('aria-describedby')!)?.textContent).toBe(
      '操作说明',
    )
    if (method === 'escape') fireEvent(dialog, new Event('cancel', { cancelable: true }))
    else if (method === 'backdrop') fireEvent.click(dialog)
    else
      fireEvent.click(
        method === 'cancel' ? cancel : within(dialog).getByRole('button', { name: '关闭' }),
      )
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(confirm).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(trigger)
  },
)
