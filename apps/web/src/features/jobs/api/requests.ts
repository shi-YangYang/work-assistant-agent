import type { Job } from '@paa/api-contracts'
import { write } from '@web/api/client'

export function retryJob(job: Job, body: { useCurrentConfig: boolean } | Record<string, never>) {
  return write(`/jobs/${job.id}/retry`, body)
}
