import type { Theme } from '@paa/api-contracts'
import { useSyncExternalStore } from 'react'

const key = 'paa.company.theme'
const eventName = 'paa-theme-change'

function preference(): Theme {
  const value = localStorage.getItem(key)
  return value === 'light' || value === 'dark' ? value : 'system'
}

function resolved(): 'light' | 'dark' {
  const value = preference()
  return value === 'system'
    ? matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light'
    : value
}

function apply() {
  document.documentElement.dataset.theme = resolved()
  window.dispatchEvent(new Event(eventName))
}

export function initializeTheme() {
  apply()
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (preference() === 'system') apply()
  })
  window.addEventListener('storage', (event) => {
    if (event.key === key || event.key === null) apply()
  })
}

function subscribe(callback: () => void) {
  window.addEventListener(eventName, callback)
  return () => window.removeEventListener(eventName, callback)
}

export function setTheme(value: Theme) {
  localStorage.setItem(key, value)
  apply()
}

export function useTheme() {
  const value = useSyncExternalStore(subscribe, preference)
  const effective = useSyncExternalStore(subscribe, resolved)
  return { value, effective, setTheme }
}
