import styles from './PageLoading.module.css'

export function PageLoading() {
  return (
    <div className={styles.loading} aria-busy="true">
      <div className={styles.content} role="status" aria-live="polite">
        <div className={styles.emblem} aria-hidden="true">
          <span className={styles.mark} />
        </div>
        <p>正在加载页面</p>
      </div>
    </div>
  )
}
