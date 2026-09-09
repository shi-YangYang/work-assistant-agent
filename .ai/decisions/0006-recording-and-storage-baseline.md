# Decision — 会议录音与本地保存实施基线

日期：2026-09-09

状态：Spec 002 已完成，真实麦克风采集、保存和重启回放已验证，恢复重试缺陷已闭环，新的独立工程验收 PASS。

## Context

用户同意开始下一份 Spec，目标是开始会议、持续录音、结束保存、重启后回放。现有 Electron / Python 控制边界已经完成，SQLite + 文件是已记录的 MVP 存储方向。ASR、LLM 和安装包继续留给后续 Spec。

## Decision

- 首版采集系统默认麦克风，一次一场会议；本轮不引入系统声音、暂停续录或录音中设备切换。
- 在 Python 内使用 sounddevice RawInputStream 采集，回调与文件写入通过有界缓冲隔离。使用普通 PCM 缓冲，不为本轮额外引入 NumPy 或推理依赖。
- 持续写 PCM16 WAV，实际采样率随设备能力校验；最终音频可用 Python 标准库 wave 处理。后续 ASR 需要的重采样与业务分块在消费者边界完成。
- SQLite 保存会议与音频元信息；音频单独存文件。数据根目录由 Electron 用户数据位置决定，Python 持久化相对路径。
- stdio 保留为控制与状态通道；音频不塞入 JSON 消息。浏览器界面通过受限会议资源回放，不能读取任意文件路径。
- 正常关闭必须先停止并保存活动录音；强制中断通过下次启动标记和文件恢复处理。

## Reason

保持录音与界面、后续推理解耦，沿用现有 Python 方向和内部进程管理。原始缓冲与标准库写入满足本轮需求，SQLite 无需额外数据库服务。WAV 便于对照有效帧数验证录音时长和后续处理。

## Alternatives

- renderer 的 getUserMedia / MediaRecorder 可承接浏览器音频采集，但会改变当前录音归属与页面生命周期关系。本轮先验证 Python 采集边界；若真实权限验证失败，再依据证据调整，不能同时实现两套采集栈。
- 压缩音频可节省空间，但本次优先避免编码器及转码链路，保留原始 PCM；磁盘占用限制需明确处理。
- 内存中累计整场录音后写文件不适合持续录音；采用持续写入与有界缓冲。

## Consequences

依赖固定为 sounddevice 0.5.6、CFFI 2.1.1、pycparser 3.0，无 NumPy。2026-09-09 在 macOS ARM64 使用默认 MacBook Pro 麦克风，Electron 查询权限为 granted，Python RawInputStream 实录单声道 PCM16 / 48000 Hz。短系统提示音经扬声器和物理麦克风采集，非 PCM 注入；最终 210944 帧、约 4.395 秒。保存后以同一隔离目录重启，历史会议可查询，播放器解码时长 4.394667 秒并正常推进播放位置。

原始实录、截图和 JSON 证据保存在忽略目录，统计与边界记入 Spec 002 实施报告；不将音频或测试数据库提交 Git。真实录音验证与后续合成故障测试分别记录。

官方支持的平台列表不能替代设备验证，Windows 状态仍需单独记录。产品能力以实际实现和最终验收报告为准。

正式用户不安装 Python / Node.js 的约束继续适用；本轮仍是开发交付，安装包内置运行时由 [决策 0005](0005-self-contained-desktop-distribution.md) 约束后续分发。详细行为与验证边界见 [Spec 002](../../specs/spec-002-meeting-recording-and-storage/spec.md)。

## 恢复重试补充

首轮独立验收复现了“原文件有完整帧，但恢复副本暂时不可写后永久跳过恢复”的问题，详见 Spec 002 [首轮报告](../../specs/spec-002-meeting-recording-and-storage/acceptance-round-1.md)。已按 [返工要求](../../specs/spec-002-meeting-recording-and-storage/rework.md) 修复并通过独立验收，不改变 schema 或媒体权限。

使用现有状态和相对路径保留待恢复关联，区分没有可恢复音频与暂时无法生成恢复副本。待恢复记录保持不可播放并提示排除存储故障后重新连接，启动时重新检查原始完整帧；恢复成功后为 interrupted，不是 completed。原始文件与错误原因保留，播放仍通过校验后的 recovered.wav。实际以 `failed` + 非空恢复目标关联表示待恢复，普通无有效候选的失败为空关联；详细语义与 13 项定向回归见 [返工报告](../../specs/spec-002-meeting-recording-and-storage/implementation-rework-1.md)。

## Sources

查阅日期：2026-09-09。上述选择为结合现有项目边界的工程判断。

- [sounddevice Raw Streams](https://python-sounddevice.readthedocs.io/en/latest/api/raw-streams.html)：支持普通缓冲形式的输入流，无需 NumPy。
- [sounddevice Installation](https://python-sounddevice.readthedocs.io/en/latest/installation.html)：macOS / Windows 的 pip 分发与 PortAudio 依赖说明；实际可用性仍需验证。
- [Python 3.12 wave](https://docs.python.org/3.12/library/wave.html)：标准库支持未压缩 PCM WAV。
- [Electron systemPreferences](https://www.electronjs.org/docs/latest/api/system-preferences)：媒体权限相关 API，平台适用范围需与原生输入流实测结合。
