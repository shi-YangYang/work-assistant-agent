import styles from './Pagination.module.css'
export function Pagination({
  page,
  hasNext,
  previous,
  next,
  className = '',
}: {
  page: number
  hasNext: boolean
  previous: () => void
  className?: string
  next: () => void
}) {
  return (
    <nav className={`${styles['list-pagination']} ${className}`} aria-label="列表分页">
      <button disabled={page === 1} onClick={previous}>
        上一页
      </button>
      <span>第 {page} 页</span>
      <button disabled={!hasNext} onClick={next}>
        下一页
      </button>
    </nav>
  )
}
