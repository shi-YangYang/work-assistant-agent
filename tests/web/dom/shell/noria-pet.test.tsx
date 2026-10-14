// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render as renderView,
  screen,
  within,
} from '@testing-library/react'
import { createRef, useState, type ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PetStage } from '../../../../apps/web/src/app/layout/pet/PetStage'
import { AppearancePage } from '../../../../apps/web/src/features/settings/components/appearance/AppearancePage'
import { initializeTheme, setTheme } from '../../../../apps/web/src/lib/theme'
import { dialogs } from '../helpers'
import { createTypingRenderer } from '../../../../apps/web/src/app/layout/pet/typing-animation'

vi.mock('../../../../apps/web/src/app/layout/pet/typing-animation', () => ({
  createTypingRenderer: vi.fn(() => vi.fn()),
}))

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
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
const render = (element: ReactElement) => renderView(element, { wrapper: MemoryRouter })

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

function mockImageRetries() {
  vi.useFakeTimers()
  const images: HTMLImageElement[] = []
  vi.stubGlobal('Image', function () {
    const image = document.createElement('img')
    const src = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src')!
    Object.defineProperty(image, 'src', {
      get: () => src.get!.call(image),
      set: (value: string) => {
        src.set!.call(image, value)
        if (value.includes('noria-retry')) images.push(image)
      },
    })
    return image
  })
  return images
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
  const trigger = screen.getByRole('button', { name: 'Noria' })
  trigger.focus()
  fireEvent.click(trigger)
  const dialog = screen.getByRole('dialog', { name: 'Noria' })
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
  const trigger = screen.getByRole('button', { name: 'Noria' })
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
  expect(screen.getByRole('button', { name: 'Noria' })).toBe(trigger)
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
  const trigger = screen.getByRole('button', { name: 'Noria' })
  const mark = trigger.querySelector('img[src*="mark"]')!
  fireEvent.error(trigger.querySelector('img[src*="blink"]')!)
  expect(trigger.querySelector('[data-animate]')?.getAttribute('data-animate')).toBe('false')
  expect(trigger.querySelector('img[src*="mark"]')).toBe(mark)
  expect(trigger.querySelector('img[src*="blink"]')).toBeNull()
  fireEvent.error(mark)
  expect(within(trigger).getByText('N')).toBeTruthy()
  expect(trigger.querySelector('img')).toBeNull()
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog', { name: 'Noria' })).toBeTruthy()
})

it('recovers failed blink and brand images without replacing the pet or showing broken images', () => {
  const retries = mockImageRetries()
  render(<PetStage {...props} animate />)
  const trigger = screen.getByRole('button', { name: 'Noria' })
  const pet = trigger.querySelector('[data-animate]')!
  const mark = trigger.querySelector('img[src*="mark"]')!
  fireEvent.error(trigger.querySelector('img[src*="blink"]')!)
  act(() => vi.advanceTimersByTime(1000))
  expect(retries).toHaveLength(1)
  expect(trigger.querySelector('img[src*="blink"]')).toBeNull()
  expect(trigger.querySelector('img[src*="mark"]')).toBe(mark)
  fireEvent.load(retries[0])
  expect(trigger.querySelector('[data-animate]')).toBe(pet)
  expect(pet.getAttribute('data-animate')).toBe('true')
  expect(trigger.querySelector('img[src*="blink"]')?.getAttribute('src')).toBe(retries[0].src)

  fireEvent.error(mark)
  act(() => vi.advanceTimersByTime(1000))
  expect(retries).toHaveLength(2)
  expect(within(trigger).getByText('N')).toBeTruthy()
  fireEvent.load(retries[1])
  expect(within(trigger).queryByText('N')).toBeNull()
  expect(pet.getAttribute('data-animate')).toBe('true')
  expect(trigger.querySelector('img[src*="mark"]')?.getAttribute('src')).toBe(retries[1].src)
  act(() => {
    vi.advanceTimersByTime(60000)
    window.dispatchEvent(new Event('online'))
  })
  expect(retries).toHaveLength(2)
})

it('bounds failed retries, resumes on reconnect or visibility, and cleans up pending work', () => {
  const retries = mockImageRetries()
  const view = render(<PetStage {...props} animate />)
  const trigger = screen.getByRole('button', { name: 'Noria' })
  fireEvent.error(trigger.querySelector('img[src*="blink"]')!)
  act(() => vi.advanceTimersByTime(1000))
  fireEvent.error(retries[0])
  act(() => vi.advanceTimersByTime(3000))
  fireEvent.error(retries[1])
  act(() => vi.advanceTimersByTime(60000))
  expect(retries).toHaveLength(2)
  expect(retries[0].src).not.toBe(retries[1].src)

  act(() => window.dispatchEvent(new Event('online')))
  expect(retries).toHaveLength(3)
  fireEvent.error(retries[2])
  setVisibility(true)
  act(() => {
    vi.advanceTimersByTime(60000)
    window.dispatchEvent(new Event('online'))
  })
  expect(retries).toHaveLength(3)
  expect(retries[2].onload).toBeNull()
  setVisibility(false)
  act(() => vi.advanceTimersByTime(1000))
  expect(retries).toHaveLength(4)
  fireEvent.error(retries[3])
  view.unmount()
  expect(retries[3].onload).toBeNull()
  expect(retries[3].onerror).toBeNull()
  act(() => {
    vi.advanceTimersByTime(60000)
    window.dispatchEvent(new Event('online'))
  })
  expect(retries).toHaveLength(4)
})

it('stays static for reduced motion and reacts when the preference changes', () => {
  reducedMotion = true
  render(<PetStage {...props} animate />)
  const pet = screen.getByRole('button', { name: 'Noria' }).querySelector('[data-animate]')!
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
  fireEvent.click(screen.getByRole('button', { name: 'Noria' }))
  act(() => {
    localStorage.setItem('paa.company.theme', 'dark')
    window.dispatchEvent(new StorageEvent('storage', { key: 'paa.company.theme' }))
  })
  expect(screen.getByRole('button', { name: '深色' }).getAttribute('aria-pressed')).toBe('true')
  expect(document.documentElement.dataset.theme).toBe('dark')
})

it('switches work state without replacing the trigger, preserves the label and pauses animation', () => {
  let image!: HTMLImageElement
  vi.stubGlobal('Image', function () {
    image = document.createElement('img')
    return image
  })
  const view = render(<PetStage {...props} animate />)
  const trigger = screen.getByRole('button', { name: 'Noria' })
  const pet = trigger.querySelector('[data-animate]')!
  const canvas = trigger.querySelector('canvas')!
  expect(canvas.dataset.ready).toBe('false')
  view.rerender(<PetStage {...props} animate activity="working" />)
  expect(screen.getByRole('status').textContent).toBe('努力工作中')
  expect(canvas.dataset.typing).toBe('false')
  fireEvent.load(image)
  expect(createTypingRenderer).toHaveBeenCalled()
  expect(canvas.dataset.typing).toBe('true')
  fireEvent.click(trigger)
  expect(canvas.dataset.typing).toBe('false')
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
  expect(canvas.dataset.typing).toBe('true')
  setVisibility(true)
  expect(canvas.dataset.typing).toBe('false')
  setVisibility(false)
  expect(canvas.dataset.typing).toBe('true')
  act(() => {
    reducedMotion = true
    motionListeners.forEach((callback) => callback())
  })
  expect(canvas.dataset.typing).toBe('false')
  expect(canvas.dataset.active).toBe('true')
  view.rerender(<PetStage {...props} animate activity="unknown" />)
  expect(screen.getByRole('status').textContent).toBe('状态待同步')
  expect(canvas.dataset.active).toBe('false')
  view.rerender(<PetStage {...props} animate activity="idle" />)
  expect(screen.queryByRole('status')).toBeNull()
  expect(trigger.querySelector('[data-animate]')).toBe(pet)
  expect(trigger.querySelector('canvas')).toBe(canvas)
  expect(fetch).not.toHaveBeenCalled()
})

it('retains the original face and working status when the working asset cannot load', () => {
  vi.useFakeTimers()
  let image!: HTMLImageElement
  vi.stubGlobal('Image', function () {
    image = document.createElement('img')
    return image
  })
  render(<PetStage {...props} animate activity="working" />)
  fireEvent.error(image)
  const trigger = screen.getByRole('button', { name: 'Noria' })
  expect(trigger.querySelector('img[src*="mark"]')).not.toBeNull()
  expect(trigger.querySelector('canvas')?.dataset.ready).toBe('false')
  expect(screen.getByRole('status').textContent).toBe('努力工作中')
})
