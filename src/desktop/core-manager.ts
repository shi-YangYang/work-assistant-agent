import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { EventEmitter } from 'node:events'
import { CoreError, JsonLineClient } from './json-line-client'
import { pythonCommand } from './python-command'
import { UNAVAILABLE_CAPABILITIES, type CoreStatus, type MeetingsResult } from '../shared/contracts'

export class CoreManager extends EventEmitter {
  private client: JsonLineClient | undefined
  private starting: Promise<CoreStatus> | undefined
  private closed = false
  private status: CoreStatus = {
    connection: 'starting',
    message: '正在连接本地核心…',
    capabilities: UNAVAILABLE_CAPABILITIES,
  }

  constructor(private readonly root: string) {
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
    if (!this.starting) {
      this.starting = this.connect().finally(() => {
        this.starting = undefined
      })
    }
    return this.starting
  }

  private async connect(): Promise<CoreStatus> {
    const previous = this.client
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
      [...args, '-u', join(this.root, 'src/python/paa_core/__main__.py')],
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
      if (!/^3\.12\./.test(health.pythonVersion)) {
        throw new CoreError('python_version', '本地核心需要 Python 3.12，请更新项目 .venv 后重试。')
      }
      if (!this.closed) {
        this.update({ connection: 'ready', message: '本地核心已连接', ...health })
      }
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

  async listMeetings(): Promise<MeetingsResult> {
    if (this.status.connection !== 'ready' || !this.client) {
      return { ok: false, message: '本地核心尚未连接，暂时无法读取会议记录。' }
    }
    const client = this.client
    try {
      const result = await client.request('meetings.list')
      // The foundation has no repository yet. Reject unexpected data instead of fabricating records.
      if (
        !result ||
        typeof result !== 'object' ||
        !('meetings' in result) ||
        !Array.isArray(result.meetings) ||
        result.meetings.length !== 0
      ) {
        throw new CoreError('invalid_meetings', '会议列表数据无效，请重新连接。')
      }
      return { ok: true, meetings: [] }
    } catch (error) {
      if (this.client === client && !this.closed) this.reportError(error)
      return { ok: false, message: '暂时无法读取会议记录，请检查本地核心连接。' }
    }
  }

  async stop(): Promise<void> {
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

function isHealth(value: unknown): value is Pick<CoreStatus, 'capabilities'> & {
  pythonVersion: string
  processId: number
} {
  if (!value || typeof value !== 'object') return false
  const health = value as Record<string, unknown>
  const capabilities = health.capabilities
  return (
    typeof health.pythonVersion === 'string' &&
    typeof health.processId === 'number' &&
    Number.isSafeInteger(health.processId) &&
    health.processId > 0 &&
    Array.isArray(capabilities) &&
    capabilities.length === 3 &&
    UNAVAILABLE_CAPABILITIES.every((expected, index) => {
      const capability = capabilities[index]
      return capability?.id === expected.id && capability.available === false
    })
  )
}
