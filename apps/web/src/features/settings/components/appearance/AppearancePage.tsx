import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import layoutStyles from '../../../../styles/layout.module.css'
import { ThemePicker } from '@web/components/appearance/ThemePicker'
import styles from './AppearancePage.module.css'

export function AppearancePage() {
  return (
    <div className={layoutStyles['settings-page']}>
      <PageHeader title="外观" />
      <div className={styles.options}>
        <ThemePicker />
      </div>
    </div>
  )
}
