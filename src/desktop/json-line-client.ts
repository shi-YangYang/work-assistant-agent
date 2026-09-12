import { type ChildProcessWithoutNullStreams } from 'node:child_process'

type Pending = {
  resolve: (result: unknown) => void
  reject: (error: Error) => void
  timer: ReturnType<typeof setTimeout>
}

export class CoreError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

export class JsonLineClient {
  private buffer = ''
  private nextId = 0
  private pending = new Map<string, Pending>()
  private failure: Error | undefined
  private stopping = false
  private closePromise: Promise<void> | undefined
  private readonly exited: Promise<void>

  constructor(
    readonly child: ChildProcessWithoutNullStreams,
    private readonly onFailure: (error: Error) => void,
    private readonly timeoutMs = 3_000,
    private readonly maxLineLength = 65_536,
  ) {
    this.exited = new Promise((resolve) => child.once('close', () => resolve()))
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => this.consume(chunk))
    // Drain stderr, but never reflect arbitrary child output or environment in the UI.
    child.stderr.on('data', () => {})
    child.stdin.on('error', () => this.fail(new CoreError('write_failed', '核心通信写入失败。')))
    child.on('error', (error: NodeJS.ErrnoException) => {
      this.fail(
        new CoreError(
          error.code === 'ENOENT' ? 'python_missing' : 'spawn_failed',
          error.code === 'ENOENT'
            ? '未找到 Python 3.12。请创建项目 .venv 或设置 PAA_PYTHON 后重试。'
            : '无法启动本地核心。请检查 Python 可执行文件及其权限后重试。',
        ),
      )
    })
    child.on('exit', () => this.fail(new CoreError('exited', '本地核心已退出，请重新连接。')))
  }

  get pendingCount(): number {
    return this.pending.size
  }

  request(
    method: string,
    timeoutMs = this.timeoutMs,
    params: Record<string, unknown> = {},
  ): Promise<unknown> {
    if (this.failure) return Promise.reject(this.failure)
    if (this.stopping) return Promise.reject(new CoreError('stopping', '本地核心正在停止。'))
    if (this.pending.size >= 64) {
      return Promise.reject(new CoreError('busy', '本地核心请求过多，请稍后重试。'))
    }
    const id = String(++this.nextId)
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new CoreError('timeout', '操作结果尚未确定，正在查询当前状态。'))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      try {
        this.child.stdin.write(JSON.stringify({ id, method, params }) + '\n', (error) => {
          if (error) this.fail(new CoreError('write_failed', '核心通信写入失败。'))
        })
      } catch {
        this.fail(new CoreError('write_failed', '核心通信写入失败。'))
      }
    })
  }

  private consume(chunk: string): void {
    if (this.failure) return
    this.buffer += chunk
    let newline: number
    while ((newline = this.buffer.indexOf('\n')) !== -1) {
      if (newline > this.maxLineLength) return this.invalidOutput()
      const line = this.buffer.slice(0, newline)
      this.buffer = this.buffer.slice(newline + 1)
      let response: unknown
      try {
        response = JSON.parse(line)
      } catch {
        return this.invalidOutput()
      }
      if (!response || typeof response !== 'object' || Array.isArray(response)) {
        return this.invalidOutput()
      }
      const message = response as Record<string, unknown>
      const hasResult = Object.hasOwn(message, 'result')
      const hasError = Object.hasOwn(message, 'error')
      if (typeof message.id !== 'string' || hasResult === hasError) return this.invalidOutput()
      if (
        hasError &&
        (!message.error ||
          typeof message.error !== 'object' ||
          !('code' in message.error) ||
          typeof message.error.code !== 'string' ||
          !('message' in message.error) ||
          typeof message.error.message !== 'string')
      ) {
        return this.invalidOutput()
      }
      const pending = this.pending.get(message.id)
      // Late responses after a timeout are harmless; ids are never reused.
      if (!pending) continue
      clearTimeout(pending.timer)
      this.pending.delete(message.id)
      if (hasError) {
        const remote = message.error as { code: string; message: string }
        const publicCodes = new Set([
          'not_configured',
          'nontext_model',
          'transcript_incomplete',
          'empty_transcript',
          'input_too_large',
          'invalid_config',
          'invalid_url',
          'invalid_parameters',
          'invalid_operation',
          'queue_full',
          'operation_missing',
          'source_missing',
          'interrupted',
          'response_too_large',
          'invalid_params',
          'invalid_id',
          'storage_error',
          'storage_unavailable',
          'storage_schema',
          'storage_commit',
          'recording_active',
          'recording_unavailable',
          'meeting_missing',
          'meeting_busy',
          'meeting_deleting',
          'invalid_title',
          'invalid_query',
          'invalid_export',
          'library_busy',
          'search_timeout',
          'snapshot_busy',
          'content_missing',
          'export_large',
          'delete_failed',
          'audio_path',
          'core_error',
        ])
        pending.reject(
          publicCodes.has(remote.code)
            ? new CoreError(remote.code, remote.message)
            : new CoreError('remote_error', '本地核心无法处理该请求。'),
        )
      } else {
        pending.resolve(message.result)
      }
    }
    if (this.buffer.length > this.maxLineLength) this.invalidOutput()
  }

  private invalidOutput(): void {
    this.fail(new CoreError('invalid_output', '本地核心返回了无效数据，请重新连接。'))
    this.child.kill()
  }

  private fail(error: Error): void {
    if (this.failure) return
    this.failure = error
    this.buffer = ''
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer)
      pending.reject(error)
    }
    this.pending.clear()
    if (!this.stopping) this.onFailure(error)
  }

  stop(): Promise<void> {
    if (!this.closePromise) this.closePromise = this.stopProcess()
    return this.closePromise
  }

  private async stopProcess(): Promise<void> {
    // Mark intentional shutdown before the process emits exit/error.
    const shutdown = this.failure
      ? Promise.resolve()
      : this.request('shutdown', 400).catch(() => {})
    this.stopping = true
    await shutdown
    this.fail(new CoreError('stopped', '本地核心已停止。'))
    this.child.stdin.end()
    if (this.child.exitCode !== null || this.child.signalCode !== null || !this.child.pid) return
    this.child.kill()
    let timer: ReturnType<typeof setTimeout> | undefined
    await Promise.race([
      this.exited,
      new Promise<void>((resolve) => {
        timer = setTimeout(() => {
          this.child.kill('SIGKILL')
          resolve()
        }, 800)
      }),
    ])
    if (timer) clearTimeout(timer)
    // SIGKILL is the bounded fallback; wait for the OS to reap before retry.
    await this.exited
  }
}
