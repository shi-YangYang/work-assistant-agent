import { dingtalkResult } from '@web/features/auth/utils/dingtalk-flow'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

export function DingTalkResult() {
  const location = useLocation()
  const navigate = useNavigate()
  const [result] = useState(() => dingtalkResult(location.search))
  useEffect(() => {
    const query = new URLSearchParams(location.search)
    if (!query.has('dingtalk')) return
    for (const key of ['dingtalk', 'reason', 'requestId']) query.delete(key)
    void navigate({ pathname: location.pathname, search: query.toString() }, { replace: true })
  }, [location.pathname, location.search, navigate])
  if (!result) return null
  const message =
    location.pathname === '/settings/login' && !result.failed
      ? '真实钉钉授权验证成功。入口是否开放仍由启用开关控制。'
      : result.message
  return (
    <div
      className={`notice${result.failed ? ' error' : ''}`}
      role={result.failed ? 'alert' : 'status'}
    >
      <span>{message}</span>
      {result.requestId && <small>请求编号：{result.requestId}</small>}
    </div>
  )
}
