import styles from './ThemePicker.module.css'
import { useTheme } from '@web/lib/theme'

export function ThemePicker() {
  const { value, setTheme } = useTheme()
  return (
    <div className={styles['theme-options']} role="group" aria-label="页面主题">
      {(['light', 'dark', 'system'] as const).map((theme) => (
        <button
          type="button"
          key={theme}
          data-selected={theme === value}
          onClick={() => setTheme(theme)}
          aria-pressed={theme === value}
        >
          <span className={styles['theme-preview']} data-theme-preview={theme} aria-hidden="true">
            <i />
            <span />
          </span>
          {{ light: '浅色', dark: '深色', system: '跟随系统' }[theme]}
        </button>
      ))}
    </div>
  )
}
