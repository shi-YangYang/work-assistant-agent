import type { Job } from '@paa/api-contracts'
import { write } from '@web/api/client'

export function retryJob(
  job: Job,
  body: { useCurrentConfig: boolean } | Record<string, never> = {},
) {
  return write<Job>(`/jobs/${job.id}/retry`, body)
}

export function cancelJob(job: Job) {
  return write<Job>(`/jobs/${job.id}/cancel`, {
    expectedAttempt: job.attempt ?? 0,
    expectedFence: job.fence ?? 0,
  })
}
