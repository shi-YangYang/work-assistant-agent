import type { Job, JobFeedback } from '@paa/api-contracts'
import { acceptFeedback, subscribeJobFeedback, visibleFeedback } from '@web/api/job-feedback'
import { useEffect, useRef, useState } from 'react'

export function useJobFeedback(job: Job | null, enabled: boolean, refresh: () => void) {
  const [value, setValue] = useState<JobFeedback | null>(null)
  const [error, setError] = useState('')
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
          setValue((current) =>
            incoming && jobId ? acceptFeedback(current, incoming, jobId) : null,
          ),
        setError,
        () => refreshRef.current(),
      ),
    [jobId, attempt, fence, state],
  )

  return {
    feedback: enabled ? visibleFeedback(job, value) : null,
    error: job && ['succeeded', 'awaiting_input', 'cancelled'].includes(job.state) ? '' : error,
  }
}
