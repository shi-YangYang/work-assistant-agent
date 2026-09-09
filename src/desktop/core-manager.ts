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
    message: '正在连接本地核心…',
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
      message: '正在连接本地核心…',
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
          message: health.storageError || '本地核心已连接',
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
  async stop(): Promise<void> {
    if (this.status.connection === 'ready') await this.finishRecording()
    this.closed = true
    const client = this.client
    this.client = undefined
    await client?.stop()
    await this.starting
    this.update({
      connection: 'stopped',
      message: '本地核心已停止',
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
        typeof capabilities[index]?.available === 'boolean' &&
        (index === 0 || capabilities[index].available === false),
    )
  )
}
