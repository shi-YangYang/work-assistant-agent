import styles from './Status.module.css'
export const statusLabel = (status: string) =>
  ({
    in_progress: '进行中',
    blocked: '有阻碍',
    done: '已完成',
    pending: '待确认',
    confirmed: '已确认',
    ignored: '已忽略',
  })[status] ?? status

export function Status({ value }: { value: string }) {
  return (
    <span className={styles['status']} data-status={value}>
      {statusLabel(value)}
    </span>
  )
}
