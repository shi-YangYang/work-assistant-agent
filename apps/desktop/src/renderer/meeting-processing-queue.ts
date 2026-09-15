import type { DesktopApi, TranscriptionStatus } from '../shared/contracts'
import type { SummaryView } from '../shared/summary-contracts'

type Listener = (label: string) => void
type Entry = {
  meetingId: string
  listeners: Set<Listener>
  label: string
  nextRefresh: number
  inFlight: boolean
}

function processingLabel(transcript: TranscriptionStatus, summary: SummaryView): string {
  const task = summary.task
  if (task?.state === 'running') return '正在生成纪要'
  if (task?.state === 'queued') return '纪要排队中'
  if (task?.state === 'failed' || task?.state === 'interrupted') return '纪要待重试'
  if (summary.result) return '纪要已就绪'
  if (transcript.state === 'completed') return '文字已完成'
  if (transcript.state === 'failed' || transcript.state === 'paused') return '转写待继续'
  if (transcript.state === 'not_started') return '尚未转写'
  if (transcript.state === 'queued') return '转写排队中'
  if (transcript.state === 'draining') return '转写收尾中'
  return '正在转写'
}

// All list rows share this budget, including requests still settling after a row leaves view.
export class MeetingProcessingQueue {
  private entries = new Map<string, Entry>()
  private inFlight = 0
  private timer: ReturnType<typeof setTimeout> | undefined

  constructor(private readonly api: Pick<DesktopApi, 'getTranscriptionStatus' | 'getSummary'>) {}

  subscribe(meetingId: string, listener: Listener): () => void {
    let entry = this.entries.get(meetingId)
    if (!entry) {
      entry = { meetingId, listeners: new Set(), label: '', nextRefresh: 0, inFlight: false }
      this.entries.set(meetingId, entry)
    }
    entry.listeners.add(listener)
    if (entry.label) listener(entry.label)
    this.pump()
    return () => {
      entry.listeners.delete(listener)
      if (!entry.listeners.size && this.isCurrent(entry)) this.entries.delete(meetingId)
      this.pump()
    }
  }

  private isCurrent(entry: Entry): boolean {
    return this.entries.get(entry.meetingId) === entry
  }

  private pump(): void {
    clearTimeout(this.timer)
    this.timer = undefined
    let next = Infinity
    for (const entry of this.entries.values()) {
      if (entry.inFlight) continue
      if (entry.nextRefresh <= Date.now() && this.inFlight < 4) {
        entry.inFlight = true
        this.inFlight++
        void this.refresh(entry)
      } else {
        next = Math.min(next, entry.nextRefresh)
      }
    }
    if (this.inFlight < 4 && next < Infinity)
      this.timer = setTimeout(() => this.pump(), Math.max(0, next - Date.now()))
  }

  private async refresh(entry: Entry): Promise<void> {
    let delay = 5000
    let label = '处理状态待刷新'
    try {
      const transcript = await this.api.getTranscriptionStatus(entry.meetingId)
      if (!this.isCurrent(entry)) return
      if (transcript.ok) {
        const summary = await this.api.getSummary(entry.meetingId)
        if (!this.isCurrent(entry)) return
        if (summary.ok) {
          label = processingLabel(transcript.value, summary.value)
          const active =
            ['queued', 'running', 'draining'].includes(transcript.value.state) ||
            (summary.value.task && ['queued', 'running'].includes(summary.value.task.state))
          // Keep idle/terminal results briefly, but still discover automatic summary handoff.
          delay = active ? 5000 : 30_000
        }
      }
    } catch {
      // A failed read can be retried while the row remains relevant.
    } finally {
      if (this.isCurrent(entry)) {
        entry.label = label
        entry.nextRefresh = Date.now() + delay
        for (const listener of entry.listeners) listener(label)
      }
      entry.inFlight = false
      this.inFlight--
      this.pump()
    }
  }
}
