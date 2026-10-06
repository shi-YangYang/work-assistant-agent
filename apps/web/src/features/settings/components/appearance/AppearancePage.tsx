import layoutStyles from '../../../../styles/layout.module.css'
import { ThemePicker } from '@web/components/appearance/ThemePicker'
import styles from './AppearancePage.module.css'

export function AppearancePage() {
  return (
    <div className={layoutStyles['settings-page']}>
      <h2>外观</h2>
      <div className={styles.options}>
        <ThemePicker />
      </div>
    </div>
  )
}
