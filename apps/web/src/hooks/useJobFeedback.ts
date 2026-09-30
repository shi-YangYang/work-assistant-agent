import type { Job, JobFeedback } from '@paa/api-contracts'
import {
  acceptFeedback,
  reconnectJobFeedback,
  subscribeJobFeedback,
  visibleFeedback,
} from '@web/api/job-feedback'
import { epoch } from '@web/api/client'
import { useEffect, useMemo, useRef, useState } from 'react'

export function useJobFeedback(
  job: Job | null,
  enabled: boolean,
  refresh: (feedback?: JobFeedback) => void,
) {
  const generation = epoch
  const [snapshot, setSnapshot] = useState<{
    generation: number
    value: JobFeedback | null
  } | null>(null)
  const [failure, setFailure] = useState<{
    generation: number
    jobId: string
    message: string
  } | null>(null)
  const value = snapshot?.generation === generation ? snapshot.value : null
  const refreshRef = useRef(refresh)
  useEffect(() => {
    refreshRef.current = refresh
  }, [refresh])
  const jobId = enabled && job?.kind === 'message' ? job.id : null
  const attempt = job?.attempt ?? 0
  const fence = job?.fence ?? 0
  const state = job?.state
  useEffect(
    () =>
      subscribeJobFeedback(
        jobId,
        state,
        attempt,
        fence,
        (incoming) =>
          setSnapshot((previous) => ({
            generation,
            value:
              incoming && jobId
                ? acceptFeedback(
                    previous?.generation === generation ? previous.value : null,
                    incoming,
                    jobId,
                  )
                : null,
          })),
        (message) =>
          setFailure((previous) =>
            previous?.generation === generation &&
            previous.jobId === jobId &&
            previous.message === message
              ? previous
              : jobId
                ? { generation, jobId, message }
                : null,
          ),
        (feedback) => refreshRef.current(feedback),
      ),
    [jobId, attempt, fence, state, generation],
  )

  const feedback = useMemo(
    () => (enabled ? visibleFeedback(job, value) : null),
    [enabled, job, value],
  )
  return {
    feedback,
    reconnect: () => reconnectJobFeedback(jobId),
    error:
      job &&
      ['queued', 'running'].includes(feedback?.state ?? job.state) &&
      failure?.generation === generation &&
      failure.jobId === job.id
        ? failure.message
        : '',
  }
}
