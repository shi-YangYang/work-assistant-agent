import utilitiesStyles from '../../../styles/utilities.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import noticeStyles from '../../../components/Notice.module.css'
import type { Job, WorkMessage } from '@paa/api-contracts'
import { stageNames } from '@web/api/job-feedback'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { retryJob } from '@web/features/jobs/api/requests'
import { TaskProgress } from './TaskProgress'
import { LoaderCircle } from 'lucide-react'
import { useRef, useState } from 'react'

export function JobNotice({
  job,
  refresh,
  showNodes = false,
  onRetryJob,
}: {
  job: NonNullable<WorkMessage['job']>
  refresh: () => void
  showNodes?: boolean
  onRetryJob?: (job: Job | null) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [confirmation, setConfirmation] = useState<'original' | 'current' | null>(null)
  const inFlight = useRef(false)
  const assistant = showNodes && job.kind === 'message'
  const progress =
    showNodes &&
    !!job.nodes?.length &&
    !(job.state === 'running' && ['preparing', 'parsing', 'transcribing'].includes(job.stage || ''))
  const reviewOnly = job.phase === 'reply_review'
  const retryLabel = progress ? '重试此步骤' : reviewOnly ? '重试答复核对' : '重试处理'
  const retry = async (useCurrentConfig = false) => {
    if (inFlight.current) return
    inFlight.current = true
    setConfirmation(null)
    setBusy(true)
    setError('')
    if (assistant)
      onRetryJob?.({
        ...job,
        attempt: (job.attempt ?? 0) + 1,
        state: 'queued',
        stage: 'queued',
        error: '',
        nodes: [],
        operationFeedback: [],
      })
    try {
      const next = await retryJob(job, useCurrentConfig ? { useCurrentConfig: true } : {})
      if (assistant) onRetryJob?.(next)
      refresh()
    } catch (e) {
      if (assistant) onRetryJob?.(null)
      setError(e as Error)
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  const confirmRetry = (mode: 'original' | 'current') => {
    setError('')
    setConfirmation(mode)
  }
  if (progress || (assistant && ['failed', 'awaiting_retry'].includes(job.state)))
    return (
      <TaskProgress
        job={error ? { ...job, error: error instanceof Error ? error.message : error } : job}
        busy={busy}
        onRetry={() => void retry()}
      />
    )
  if (job.state === 'succeeded' || job.state === 'cancelled') return null
  if (job.state === 'awaiting_input')
    return (
      <p className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
        可继续发送消息补充信息。
      </p>
    )
  if (job.state === 'queued' || job.state === 'running')
    return (
      <p className={noticeStyles['processing']} role="status">
        <LoaderCircle size={14} aria-hidden="true" />
        {job.state === 'queued' ? stageNames.queued : stageNames[job.stage || ''] || '正在处理…'}
      </p>
    )
  return (
    <>
      <div
        className={`${noticeStyles['notice']} ${utilitiesStyles['error']} ${noticeStyles['slot-error']}`}
      >
        <span>{job.error}</span>
        {!confirmation && <ErrorNotice>{error}</ErrorNotice>}
        <BusyButton
          busy={busy}
          onClick={() => (job.state === 'awaiting_retry' ? confirmRetry('original') : void retry())}
        >
          {retryLabel}
        </BusyButton>
        <BusyButton busy={busy} onClick={() => confirmRetry('current')}>
          使用当前配置重新处理
        </BusyButton>
      </div>
      {confirmation && (
        <Modal
          title={confirmation === 'current' ? '使用当前配置重新处理' : retryLabel}
          onClose={() => setConfirmation(null)}
        >
          <p>
            {confirmation === 'current'
              ? '将使用管理员最新分配的模型重新处理，已确认的内容会保留。'
              : '将使用这条消息原来的模型配置重新处理。'}
          </p>
          {reviewOnly && <p>仅重新核对已有答复，已保存的业务操作不会重复执行。</p>}
          <p className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
            模型服务可能已处理过上次请求，重试可能再次产生用量。
          </p>
          <ErrorNotice>{error}</ErrorNotice>
          <div className={layoutStyles['form-actions']}>
            <button disabled={busy} onClick={() => setConfirmation(null)}>
              取消
            </button>
            <BusyButton
              busy={busy}
              className={controlsStyles['primary']}
              onClick={() => void retry(confirmation === 'current')}
            >
              确认重试
            </BusyButton>
          </div>
        </Modal>
      )}
    </>
  )
}
