import { ArrowLeft } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { detailReturn, type ReturnPoint } from '@web/utils/navigation'
import styles from './DetailBackLink.module.css'
import controls from '@web/styles/controls.module.css'

export function DetailBackLink({ fallback }: { fallback?: ReturnPoint }) {
  const location = useLocation()
  const back = detailReturn(location.pathname, location.state, fallback)
  return (
    <Link className={`${controls['text-button']} ${styles.back}`} to={back.path} state={back.state}>
      <ArrowLeft size={15} aria-hidden="true" />
      返回{back.label}
    </Link>
  )
}
