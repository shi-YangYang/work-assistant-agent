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
import { useLayoutEffect, useRef, useState } from 'react'

function jobVersion(job: Job) {
  return JSON.stringify([
    job.id,
    job.kind,
    job.attempt,
    job.fence,
    job.state,
    job.phase,
    job.updatedAt,
  ])
}

interface JobNoticeProps {
  job: NonNullable<WorkMessage['job']>
  refresh: () => void
  showNodes?: boolean
  retryBlocked?: boolean
  onRetryStart?: () => boolean
  onRetrySettled?: (job: Job | null) => void
  onRetryJob?: (job: Job | null) => void
}

export function JobNotice(props: JobNoticeProps) {
  const signature = jobVersion(props.job)
  const [source, setSource] = useState({ signature, optimistic: '' })
  if (source.signature !== signature && source.optimistic !== signature)
    setSource({ signature, optimistic: '' })
  return (
    <JobRetryNotice
      key={source.signature}
      {...props}
      onOptimistic={(job) => setSource({ ...source, optimistic: jobVersion(job) })}
    />
  )
}

function JobRetryNotice({
  job: sourceJob,
  refresh,
  showNodes = false,
  onRetryJob,
  retryBlocked = false,
  onRetryStart,
  onRetrySettled,
  onOptimistic,
}: JobNoticeProps & {
  onOptimistic: (job: Job) => void
}) {
  const [local, setLocal] = useState({
    busy: false,
    retrying: null as Job | null,
    error: '' as Error | string,
    confirmation: null as 'original' | 'current' | null,
  })
  const { retrying, error, confirmation, busy } = local
  const current = useRef<{ request: object | null } | null>(null)
  const update = (next: Partial<typeof local>) => setLocal((previous) => ({ ...previous, ...next }))
  useLayoutEffect(() => {
    // Only committed renders acquire ownership; abandoned renders cannot invalidate a retry.
    const committed = { request: null }
    current.current = committed
    return () => {
      if (current.current === committed) current.current = null
    }
  }, [])
  const job = retrying ?? sourceJob
  const report = job.kind === 'report'
  const assistant = showNodes && job.kind === 'message'
  const progress =
    showNodes &&
    !!job.nodes?.length &&
    !(job.state === 'running' && ['preparing', 'parsing', 'transcribing'].includes(job.stage || ''))
  const reviewOnly = job.phase === 'reply_review'
  const retryLabel = progress ? '重试此步骤' : reviewOnly ? '重试答复核对' : '重试处理'
  const retry = async (useCurrentConfig = false) => {
    const committed = current.current
    if (!committed || committed.request || retryBlocked || (onRetryStart && !onRetryStart())) return
    const request = {}
    committed.request = request
    const valid = () => current.current === committed && committed.request === request
    update({
      busy: true,
      confirmation: null,
      error: '',
      retrying: report ? { ...job, state: 'queued', stage: 'queued', error: '' } : null,
    })
    if (assistant) {
      const optimistic: Job = {
        ...job,
        attempt: (job.attempt ?? 0) + 1,
        state: 'queued',
        stage: 'queued',
        error: '',
        nodes: [],
        operationFeedback: [],
      }
      // The parent echoes this optimistic snapshot before the retry request completes.
      onOptimistic(optimistic)
      onRetryJob?.(optimistic)
    }
    try {
      const next = await retryJob(job, useCurrentConfig || report ? { useCurrentConfig: true } : {})
      onRetrySettled?.(next)
      if (!valid()) return
      if (report) update({ retrying: next })
      if (assistant) onRetryJob?.(next)
      if (valid()) refresh()
    } catch (e) {
      onRetrySettled?.(null)
      if (!valid()) return
      update({ retrying: null, error: e as Error })
      if (assistant) onRetryJob?.(null)
    } finally {
      if (valid()) {
        committed.request = null
        update({ busy: false })
      }
    }
  }
  const confirmRetry = (mode: 'original' | 'current') => {
    update({ error: '', confirmation: mode })
  }
  if (progress || (assistant && ['failed', 'awaiting_retry'].includes(job.state)))
    return (
      <TaskProgress
        job={error ? { ...job, error: error instanceof Error ? error.message : error } : job}
        busy={busy}
        disabled={retryBlocked}
        onRetry={() => void retry()}
      />
    )
  if (job.state === 'cancelled')
    return assistant ? (
      <p className={utilitiesStyles['muted']} role="status">
        已中断
      </p>
    ) : null
  if (job.state === 'succeeded') return null
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
        {report
          ? job.state === 'queued'
            ? '已开始生成，正在排队…'
            : '正在生成报告…'
          : job.state === 'queued'
            ? stageNames.queued
            : stageNames[job.stage || ''] || '正在处理…'}
      </p>
    )
  if (report)
    return (
      <div
        className={`${noticeStyles['notice']} ${utilitiesStyles['error']} ${noticeStyles['slot-error']}`}
      >
        <span>{error ? (error instanceof Error ? error.message : error) : job.error}</span>
        <BusyButton busy={busy} disabled={retryBlocked} onClick={() => void retry(true)}>
          重试
        </BusyButton>
      </div>
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
          disabled={retryBlocked}
          onClick={() => (job.state === 'awaiting_retry' ? confirmRetry('original') : void retry())}
        >
          {retryLabel}
        </BusyButton>
        <BusyButton busy={busy} disabled={retryBlocked} onClick={() => confirmRetry('current')}>
          使用当前配置重新处理
        </BusyButton>
      </div>
      {confirmation && (
        <Modal
          title={confirmation === 'current' ? '使用当前配置重新处理' : retryLabel}
          onClose={() => update({ confirmation: null })}
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
            <button disabled={busy} onClick={() => update({ confirmation: null })}>
              取消
            </button>
            <BusyButton
              busy={busy}
              disabled={retryBlocked}
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
