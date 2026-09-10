import type { RuntimeConfig } from '../shared/summary-contracts'
import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { EventEmitter } from 'node:events'
import { CoreError, JsonLineClient } from './json-line-client'
import { pythonCommand } from './python-command'
import {
  ACTIVE_STATES,
  ID_PATTERN,
  UNAVAILABLE_CAPABILITIES,
  type CoreStatus,
  type Meeting,
  type MeetingsResult,
  type ModelState,
  type TranscriptionStatus,
  type TranscriptPage,
  type RecordingStatus,
  type Result,
} from '../shared/contracts'

type InternalMeeting = Meeting & { audioPath?: string }
const states = [...ACTIVE_STATES, 'completed', 'interrupted', 'failed']
function isMeeting(value: unknown): value is InternalMeeting {
  if (!value || typeof value !== 'object') return false
  const row = value as InternalMeeting
  return (
    typeof row.id === 'string' &&
    ID_PATTERN.test(row.id) &&
    typeof row.title === 'string' &&
    typeof row.createdAt === 'string' &&
    states.includes(row.status) &&
    Number.isFinite(row.durationMs) &&
    row.durationMs >= 0 &&
    typeof row.audioAvailable === 'boolean' &&
    Number.isSafeInteger(row.frames) &&
    row.frames >= 0 &&
    Number.isSafeInteger(row.sampleRate) &&
    row.sampleRate > 0 &&
    row.channels === 1 &&
    row.sampleWidth === 2 &&
    (row.audioPath === undefined || typeof row.audioPath === 'string')
  )
}
function isRecording(value: unknown): value is RecordingStatus {
  if (!value || typeof value !== 'object') return false
  const row = value as RecordingStatus
  return (
    (row.meetingId === null ||
      (typeof row.meetingId === 'string' && ID_PATTERN.test(row.meetingId))) &&
    [...states, 'idle'].includes(row.state) &&
    Number.isFinite(row.elapsedMs) &&
    row.elapsedMs >= 0 &&
    Number.isFinite(row.inputLevel) &&
    row.inputLevel >= 0 &&
    row.inputLevel <= 1 &&
    (row.error === null ||
      (typeof row.error?.code === 'string' && typeof row.error?.message === 'string'))
  )
}

export class CoreManager extends EventEmitter {
  private client: JsonLineClient | undefined
  private starting: Promise<CoreStatus> | undefined
  private statusRequest: Promise<Result<RecordingStatus>> | undefined
  private closed = false
  private status: CoreStatus = {
    connection: 'starting',
    message: '正在连接…',
    capabilities: UNAVAILABLE_CAPABILITIES,
  }
  constructor(
    private readonly root: string,
    private readonly dataRoot: string,
  ) {
    super()
  }
  getStatus(): CoreStatus {
    return this.status
  }
  private update(status: CoreStatus): void {
    this.status = status
    this.emit('status', status)
  }
  start(): Promise<CoreStatus> {
    if (this.closed) return Promise.resolve(this.status)
    if (!this.starting)
      this.starting = this.connect().finally(() => {
        this.starting = undefined
      })
    return this.starting
  }
  private async connect(): Promise<CoreStatus> {
    const previous = this.client
    if (previous && this.status.connection === 'ready') {
      const recording = await this.recordingStatus()
      if (!recording.ok) throw new CoreError('state_unknown', recording.message)
      if (ACTIVE_STATES.includes(recording.value.state))
        throw new CoreError('recording_active', '请先停止并保存当前录音。')
    }
    this.client = undefined
    this.update({
      connection: 'starting',
      message: '正在连接…',
      capabilities: UNAVAILABLE_CAPABILITIES,
    })
    await previous?.stop()
    if (this.closed) return this.status
    const { command, args } = pythonCommand(this.root)
    const child = spawn(
      command,
      [
        ...args,
        '-u',
        join(this.root, 'src/python/paa_core/__main__.py'),
        '--data-dir',
        this.dataRoot,
      ],
      {
        cwd: this.root,
        shell: false,
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      },
    )
    const client = new JsonLineClient(child, (error) => {
      if (this.client === client && !this.closed) this.reportError(error)
    })
    this.client = client
    try {
      const health = await client.request('health')
      if (!isHealth(health)) throw new CoreError('invalid_health', '本地核心状态无效，请重新连接。')
      if (!/^3\.12\./.test(health.pythonVersion))
        throw new CoreError('python_version', '本地核心需要 Python 3.12，请更新项目 .venv 后重试。')
      if (!this.closed)
        this.update({
          connection: 'ready',
          message: health.storageError || '已连接',
          ...health,
        })
    } catch (error) {
      if (!this.closed) this.reportError(error)
      this.client = undefined
      await client.stop()
    }
    return this.status
  }
  private reportError(error: unknown): void {
    this.update({
      connection: 'error',
      message: error instanceof CoreError ? error.message : '无法连接本地核心，请重试。',
      capabilities: UNAVAILABLE_CAPABILITIES,
    })
  }
  private async request(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
    if (this.status.connection !== 'ready' || !this.client)
      throw new CoreError('disconnected', '本地核心尚未连接，请重新连接以恢复会议记录。')
    return this.client.request(method, undefined, params)
  }
  private failure(error: unknown): { ok: false; message: string; code?: string } {
    return {
      ok: false,
      message: error instanceof Error ? error.message : '操作失败，请重试。',
      code: error instanceof CoreError ? error.code : undefined,
    }
  }
  async listMeetings(offset = 0): Promise<MeetingsResult> {
    try {
      const result = (await this.request('meetings.list', { offset })) as {
        meetings: unknown[]
        hasMore: boolean
      }
      if (
        !result ||
        !Array.isArray(result.meetings) ||
        !result.meetings.every(isMeeting) ||
        typeof result.hasMore !== 'boolean'
      )
        throw new CoreError('invalid_meetings', '会议列表数据无效。')
      return {
        ok: true,
        meetings: result.meetings.map((item) => this.publicMeeting(item as InternalMeeting)),
        hasMore: result.hasMore,
      }
    } catch (error) {
      return this.failure(error)
    }
  }
  private publicMeeting(meeting: InternalMeeting): Meeting {
    const publicFields = { ...meeting }
    delete publicFields.audioPath
    return publicFields
  }
  async internalMeeting(meetingId: string): Promise<InternalMeeting> {
    const result = await this.request('meetings.get', { meetingId })
    if (!isMeeting(result)) throw new CoreError('invalid_meeting', '会议详情数据无效。')
    return result
  }
  async getMeeting(meetingId: string): Promise<Result<Meeting>> {
    try {
      return { ok: true, value: this.publicMeeting(await this.internalMeeting(meetingId)) }
    } catch (error) {
      return this.failure(error)
    }
  }
  recordingStatus(): Promise<Result<RecordingStatus>> {
    if (!this.statusRequest)
      this.statusRequest = this.recordingRequest('recording.status').finally(() => {
        this.statusRequest = undefined
      })
    return this.statusRequest
  }
  private async recordingRequest(
    method: string,
    params: Record<string, unknown> = {},
  ): Promise<Result<RecordingStatus>> {
    try {
      const result = await this.request(method, params)
      if (!isRecording(result)) throw new CoreError('invalid_recording', '录音状态数据无效。')
      return { ok: true, value: result }
    } catch (error) {
      // A lost reply never justifies replaying a mutation. Query authoritative state.
      if (method !== 'recording.status' && error instanceof CoreError && error.code === 'timeout')
        return this.recordingStatus()
      return this.failure(error)
    }
  }
  startRecording(operationId: string): Promise<Result<RecordingStatus>> {
    return this.recordingRequest('recording.start', { operationId })
  }
  stopRecording(meetingId: string, interrupt = false): Promise<Result<RecordingStatus>> {
    return this.recordingRequest(interrupt ? 'recording.interrupt' : 'recording.stop', {
      meetingId,
    })
  }
  async finishRecording(interrupt = false): Promise<void> {
    const initial = await this.recordingStatus()
    if (!initial.ok) throw new Error(initial.message)
    if (!ACTIVE_STATES.includes(initial.value.state) || !initial.value.meetingId) return
    const response = await this.stopRecording(initial.value.meetingId, interrupt)
    if (!response.ok) throw new Error(response.message)
    const deadline = Date.now() + 15_000
    while (Date.now() < deadline) {
      const result = await this.recordingStatus()
      if (!result.ok) throw new Error(result.message)
      if (!ACTIVE_STATES.includes(result.value.state)) {
        if (result.value.state !== 'completed' && !interrupt)
          throw new Error(result.value.error?.message || '录音未完整保存，请检查会议记录后重试。')
        return
      }
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    throw new Error('录音仍在保存，窗口会保持打开；请稍后查看状态。')
  }
  async modelState(
    action: 'status' | 'download' | 'cancel' = 'status',
  ): Promise<Result<ModelState>> {
    try {
      const value = await this.request(`model.${action}`)
      if (!isModelState(value)) throw new CoreError('invalid_model', '模型状态数据无效。')
      const available = value.state === 'ready'
      if (
        this.status.capabilities.find((item) => item.id === 'transcription')?.available !==
        available
      )
        this.update({
          ...this.status,
          capabilities: this.status.capabilities.map((item) =>
            item.id === 'transcription' ? { ...item, available } : item,
          ),
        })
      return { ok: true, value }
    } catch (error) {
      if (action !== 'status' && error instanceof CoreError && error.code === 'timeout')
        return this.modelState()
      return this.failure(error)
    }
  }
  async transcriptionStatus(
    meetingId: string,
    start = false,
  ): Promise<Result<TranscriptionStatus>> {
    try {
      const value = await this.request(start ? 'transcription.start' : 'transcription.status', {
        meetingId,
      })
      if (!isTranscription(value) || value.meetingId !== meetingId)
        throw new CoreError('invalid_transcription', '转写状态数据无效。')
      return { ok: true, value }
    } catch (error) {
      if (start && error instanceof CoreError && error.code === 'timeout')
        return this.transcriptionStatus(meetingId)
      return this.failure(error)
    }
  }
  async transcript(meetingId: string, cursor: number): Promise<Result<TranscriptPage>> {
    try {
      const value = await this.request('transcript.list', { meetingId, cursor })
      if (!isTranscriptPage(value, meetingId, cursor))
        throw new CoreError('invalid_transcript', '转写文字数据无效。')
      return { ok: true, value }
    } catch (error) {
      return this.failure(error)
    }
  }
  async transcriptionActive(): Promise<boolean> {
    const value = (await this.request('transcription.activity')) as { active?: unknown }
    if (!value || typeof value.active !== 'boolean')
      throw new CoreError('invalid_transcription', '无法确认转写状态。')
    return value.active
  }
  async configureSummary(config: RuntimeConfig | null, automatic: boolean): Promise<void> {
    await this.request('summary.configure', { config, automatic })
    this.update({
      ...this.status,
      capabilities: this.status.capabilities.map((item) =>
        item.id === 'summary' ? { ...item, available: !!config } : item,
      ),
    })
  }
  async summaryRequest<T>(
    method:
      | 'summary.get'
      | 'summary.generate'
      | 'summary.source'
      | 'summary.operation'
      | 'summary.operationStatus'
      | 'summary.cancelOperations'
      | 'summary.validateModel'
      | 'summary.forgetModels',
    params: Record<string, unknown>,
  ): Promise<Result<T>> {
    try {
      return { ok: true, value: (await this.request(method, params)) as T }
    } catch (error) {
      return this.failure(error)
    }
  }
  async pauseTranscription(): Promise<void> {
    await this.request('transcription.pause')
  }
  async stop(): Promise<void> {
    if (this.status.connection === 'ready') await this.finishRecording()
    this.closed = true
    const client = this.client
    this.client = undefined
    await client?.stop()
    await this.starting
    this.update({
      connection: 'stopped',
      message: '连接已关闭',
      capabilities: UNAVAILABLE_CAPABILITIES,
    })
  }
}
function isHealth(value: unknown): value is Pick<CoreStatus, 'capabilities' | 'storageError'> & {
  pythonVersion: string
  processId: number
} {
  if (!value || typeof value !== 'object') return false
  const health = value as Record<string, unknown>
  const capabilities = health.capabilities
  return (
    typeof health.pythonVersion === 'string' &&
    Number.isSafeInteger(health.processId) &&
    Number(health.processId) > 0 &&
    Array.isArray(capabilities) &&
    capabilities.length === 3 &&
    UNAVAILABLE_CAPABILITIES.every(
      (expected, index) =>
        capabilities[index]?.id === expected.id &&
        typeof capabilities[index]?.available === 'boolean',
    )
  )
}
function isModelState(value: unknown): value is ModelState {
  if (!value || typeof value !== 'object') return false
  const row = value as ModelState
  return (
    typeof row.modelId === 'string' &&
    typeof row.revision === 'string' &&
    ['missing', 'downloading', 'verifying', 'ready', 'error'].includes(row.state) &&
    Number.isSafeInteger(row.downloadedBytes) &&
    row.downloadedBytes >= 0 &&
    Number.isSafeInteger(row.totalBytes) &&
    row.totalBytes > 0 &&
    row.downloadedBytes <= row.totalBytes &&
    Number.isSafeInteger(row.requiredBytes) &&
    row.requiredBytes >= row.totalBytes &&
    typeof row.source === 'string' &&
    typeof row.license === 'string' &&
    (row.error === null || typeof row.error === 'string')
  )
}
function isTranscription(value: unknown): value is TranscriptionStatus {
  if (!value || typeof value !== 'object') return false
  const row = value as TranscriptionStatus
  return (
    typeof row.meetingId === 'string' &&
    ID_PATTERN.test(row.meetingId) &&
    ['not_started', 'queued', 'running', 'draining', 'completed', 'paused', 'failed'].includes(
      row.state,
    ) &&
    [row.processedMs, row.audioMs, row.pendingMs].every((x) => Number.isSafeInteger(x) && x >= 0) &&
    (row.targetFrames === null ||
      (Number.isSafeInteger(row.targetFrames) && row.targetFrames >= 0)) &&
    typeof row.sourceIncomplete === 'boolean' &&
    (row.error === null || typeof row.error === 'string')
  )
}
function isTranscriptPage(
  value: unknown,
  meetingId: string,
  cursor: number,
): value is TranscriptPage {
  if (!value || typeof value !== 'object') return false
  const page = value as TranscriptPage
  let previous = cursor
  if (
    !Array.isArray(page.segments) ||
    page.segments.length > 100 ||
    typeof page.hasMore !== 'boolean'
  )
    return false
  for (const segment of page.segments) {
    if (
      typeof segment.id !== 'string' ||
      typeof segment.chunkId !== 'string' ||
      segment.meetingId !== meetingId ||
      !Number.isSafeInteger(segment.sequence) ||
      segment.sequence <= previous ||
      !Number.isSafeInteger(segment.startMs) ||
      segment.startMs < 0 ||
      !Number.isSafeInteger(segment.endMs) ||
      segment.endMs < segment.startMs ||
      typeof segment.text !== 'string' ||
      !segment.text.trim() ||
      segment.text.length > 300 ||
      segment.speaker !== null ||
      segment.confidence !== null
    )
      return false
    previous = segment.sequence
  }
  return page.nextCursor === previous && (!page.hasMore || page.segments.length > 0)
}
