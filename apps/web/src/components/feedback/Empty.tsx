import styles from './Empty.module.css'
import type { ReactNode } from 'react'

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={styles['empty']}>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  )
}
