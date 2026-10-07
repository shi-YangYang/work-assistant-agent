import { ArrowLeft } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { detailReturn, type ReturnPoint } from '@web/utils/navigation'
import styles from './DetailBackLink.module.css'
import controls from '@web/styles/controls.module.css'

export function DetailBackLink({
  fallback,
  destination,
  label,
  replace = false,
  embedded = false,
}: {
  fallback?: ReturnPoint
  destination?: Pick<ReturnPoint, 'path' | 'state'>
  label?: string
  replace?: boolean
  embedded?: boolean
}) {
  const location = useLocation()
  const back = destination ?? detailReturn(location.pathname, location.state, fallback)
  return (
    <Link
      className={`${controls['text-button']} ${styles.back} ${embedded ? styles.embedded : ''}`}
      to={back.path}
      state={back.state}
      replace={replace}
    >
      <ArrowLeft size={15} aria-hidden="true" />
      {label ?? `返回${'label' in back ? back.label : ''}`}
    </Link>
  )
}
