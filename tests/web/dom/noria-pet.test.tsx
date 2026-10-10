// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { createRef, useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PetStage } from '../../../apps/web/src/app/layout/pet/PetStage'
import { AppearancePage } from '../../../apps/web/src/features/settings/components/appearance/AppearancePage'
import { initializeTheme, setTheme } from '../../../apps/web/src/lib/theme'
import { dialogs } from './helpers'

let reducedMotion = false
const motionListeners = new Set<() => void>()

beforeEach(() => {
  dialogs()
  localStorage.clear()
  reducedMotion = false
  motionListeners.clear()
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query === '(prefers-reduced-motion: reduce)' && reducedMotion,
    addEventListener: (_event: string, callback: () => void) => {
      if (query === '(prefers-reduced-motion: reduce)') motionListeners.add(callback)
    },
    removeEventListener: (_event: string, callback: () => void) => {
      motionListeners.delete(callback)
    },
  }))
  vi.stubGlobal('fetch', vi.fn())
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  setTheme('light')
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
const props = {
  navTriggerRef: createRef<HTMLButtonElement>(),
  expandedNav: false,
  setExpandedNav: vi.fn(),
}

function setVisibility(hidden: boolean) {
  act(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: hidden })
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

it('shares theme controls with settings, keeps drafts, restores focus, and makes no business requests', () => {
  function View() {
    const [draft, setDraft] = useState('未发送的消息')
    return (
      <>
        <PetStage {...props} animate />
        <textarea
          aria-label="草稿"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <AppearancePage />
      </>
    )
  }
  render(<View />)
  const trigger = screen.getByRole('button', { name: 'Noria 外观' })
  trigger.focus()
  fireEvent.click(trigger)
  const dialog = screen.getByRole('dialog', { name: 'Noria 外观' })
  fireEvent.click(within(dialog).getByRole('button', { name: '深色' }))
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(localStorage.getItem('paa.company.theme')).toBe('dark')
  expect(
    screen
      .getAllByRole('button', { name: '深色' })
      .every((button) => button.getAttribute('aria-pressed') === 'true'),
  ).toBe(true)
  fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('未发送的消息')
  fireEvent.click(screen.getByRole('button', { name: '跟随系统' }))
  fireEvent.click(trigger)
  expect(
    within(screen.getByRole('dialog'))
      .getByRole('button', { name: '跟随系统' })
      .getAttribute('aria-pressed'),
  ).toBe('true')
  expect(fetch).not.toHaveBeenCalled()
})

it('keeps the same pet and brand image across page changes and pauses while hidden', () => {
  const view = render(<PetStage {...props} animate />)
  const trigger = screen.getByRole('button', { name: 'Noria 外观' })
  const pet = trigger.querySelector('[data-animate]')!
  const mark = trigger.querySelector('img[src*="mark"]')!
  const blink = trigger.querySelector('img[src*="blink"]')!
  expect(pet.getAttribute('data-animate')).toBe('true')
  expect(mark).not.toBeNull()
  expect(blink).not.toBeNull()
  setVisibility(true)
  expect(pet.getAttribute('data-paused')).toBe('true')
  setVisibility(false)
  expect(pet.getAttribute('data-paused')).toBe('false')
  view.rerender(<PetStage {...props} animate={false} />)
  expect(screen.getByRole('button', { name: 'Noria 外观' })).toBe(trigger)
  expect(trigger.querySelector('[data-animate]')).toBe(pet)
  expect(trigger.querySelector('img[src*="mark"]')).toBe(mark)
  expect(trigger.querySelector('img[src*="blink"]')).toBe(blink)
  expect(pet.getAttribute('data-animate')).toBe('false')
  setVisibility(true)
  setVisibility(false)
  expect(pet.getAttribute('data-animate')).toBe('false')
  view.rerender(<PetStage {...props} animate />)
  expect(pet.getAttribute('data-animate')).toBe('true')
  expect(trigger.querySelector('img[src*="mark"]')).toBe(mark)
  expect(trigger.querySelector('img[src*="blink"]')).toBe(blink)
})

it('keeps the brand image if blinking fails and a usable fallback if the brand image fails', () => {
  render(<PetStage {...props} animate />)
  const trigger = screen.getByRole('button', { name: 'Noria 外观' })
  const mark = trigger.querySelector('img[src*="mark"]')!
  fireEvent.error(trigger.querySelector('img[src*="blink"]')!)
  expect(trigger.querySelector('[data-animate]')?.getAttribute('data-animate')).toBe('false')
  expect(trigger.querySelector('img[src*="mark"]')).toBe(mark)
  expect(trigger.querySelector('img[src*="blink"]')).toBeNull()
  fireEvent.error(mark)
  expect(within(trigger).getByText('N')).toBeTruthy()
  expect(trigger.querySelector('img')).toBeNull()
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog', { name: 'Noria 外观' })).toBeTruthy()
})

it('stays static for reduced motion and reacts when the preference changes', () => {
  reducedMotion = true
  render(<PetStage {...props} animate />)
  const pet = screen.getByRole('button', { name: 'Noria 外观' }).querySelector('[data-animate]')!
  expect(pet.getAttribute('data-animate')).toBe('false')
  act(() => {
    reducedMotion = false
    motionListeners.forEach((callback) => callback())
  })
  expect(pet.getAttribute('data-animate')).toBe('true')
  act(() => {
    reducedMotion = true
    motionListeners.forEach((callback) => callback())
  })
  expect(pet.getAttribute('data-animate')).toBe('false')
})

it('reflects theme preferences changed in another browser tab through the existing store', () => {
  initializeTheme()
  render(<PetStage {...props} animate={false} />)
  fireEvent.click(screen.getByRole('button', { name: 'Noria 外观' }))
  act(() => {
    localStorage.setItem('paa.company.theme', 'dark')
    window.dispatchEvent(new StorageEvent('storage', { key: 'paa.company.theme' }))
  })
  expect(screen.getByRole('button', { name: '深色' }).getAttribute('aria-pressed')).toBe('true')
  expect(document.documentElement.dataset.theme).toBe('dark')
})
