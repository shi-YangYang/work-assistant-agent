import type { Theme } from '@paa/api-contracts'
import { useEffect, useState } from 'react'

function applyTheme(value: Theme) {
  localStorage.setItem('paa.company.theme', value)
  document.documentElement.dataset.theme =
    value === 'system'
      ? matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : value
}

export function AppearancePage() {
  const [value, setValue] = useState<Theme>(
    () => (localStorage.getItem('paa.company.theme') as Theme) || 'system',
  )
  useEffect(() => {
    applyTheme(value)
    const media = matchMedia('(prefers-color-scheme: dark)')
    const change = () => applyTheme(value)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [value])
  return (
    <div className="settings-page">
      <h2>外观</h2>
      <div className="theme-options">
        {(['light', 'dark', 'system'] as const).map((theme) => (
          <button
            key={theme}
            className={theme === value ? 'selected' : ''}
            onClick={() => setValue(theme)}
            aria-pressed={theme === value}
          >
            <div className={`theme-preview ${theme}`}>
              <i />
              <span />
            </div>
            {{ light: '浅色', dark: '深色', system: '跟随系统' }[theme]}
          </button>
        ))}
      </div>
    </div>
  )
}
