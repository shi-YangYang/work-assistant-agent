import layoutStyles from '../../../styles/layout.module.css'
import styles from './AppearancePage.module.css'
import { useTheme } from '@web/lib/theme'

export function AppearancePage() {
  const { value, setTheme } = useTheme()
  return (
    <div className={layoutStyles['settings-page']}>
      <h2>外观</h2>
      <div className={styles['theme-options']}>
        {(['light', 'dark', 'system'] as const).map((theme) => (
          <button
            key={theme}
            data-selected={theme === value}
            onClick={() => setTheme(theme)}
            aria-pressed={theme === value}
          >
            <div className={styles['theme-preview']} data-theme-preview={theme}>
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
