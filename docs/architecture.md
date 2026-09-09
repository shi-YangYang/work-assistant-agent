# 技术架构

状态：Spec 002 录音与本地保存已完成，恢复重试缺陷已修复，独立工程验收 [PASS](../specs/spec-002-meeting-recording-and-storage/acceptance.md)。本文记录实际接口与存储实现；真实设备和自动检查证据见实施及返工报告。

## 职责与数据流

```text
React / TypeScript 界面
    ↓ 类型化 preload API
Electron 主进程
    ↓ JSON Lines 控制 / 状态（stdin / stdout）
Python 本地核心
    ├─ 默认麦克风 → RawInputStream → 有界缓冲 → WAV 文件
    └─ Repository → SQLite 会议元信息

界面播放器 → paa-audio://meeting/<会议 ID> → 主进程校验 → WAV 文件流
```

| 模块 | 位置 | 职责 |
| --- | --- | --- |
| 主进程 | `src/desktop/main.ts` | 窗口、权限、单实例、退出 / 重连 / 系统中断协调 |
| 核心管理 | `src/desktop/core-manager.ts`、`json-line-client.ts` | 管理 Python 进程、有限控制请求、状态校验与超时查询 |
| preload / 契约 | `src/desktop/preload.ts`、`src/shared/contracts.ts` | 公开类型化业务 API，不公开任意 IPC、路径或进程执行 |
| 媒体资源 | `src/desktop/media.ts` | 校验会议 ID、存储路径及文件，提供 WAV 流与字节范围请求 |
| renderer | `src/renderer/` | 会议工作区、历史详情与播放器；展示真实状态，不直接操作 Node / Python |
| 采集与文件 | `src/python/paa_core/recorder.py`、`audio_store.py` | 设备输入、回调队列、写入、收尾及可恢复文件 |
| 持久化 | `src/python/paa_core/repository.py` | SQLite、会议查询、启动恢复、音频可用性检查 |
| 核心协议 | `src/python/paa_core/protocol.py` | 控制请求与响应，日志使用 stderr |

录音回调只复制有界音频块并更新顺序信息，文件写入在工作线程完成。音频不经过 JSON 控制协议，不在 renderer 中采集，不加入尚未使用的推理依赖。输入队列积压、设备中断或写入失败必须显式结束并报告。

## 桌面接口

| API | 用途 |
| --- | --- |
| `getStatus()` / `onStatusChanged(listener)` | 核心连接与录音 / 转写 / 总结能力，订阅返回取消函数 |
| `retryCore()` | 经过活动录音保护后重连 |
| `listMeetings(offset)` | 每页最多 50 条，返回 `hasMore`；空列表与读取失败分别表示 |
| `getMeeting(id)` | 获取详情和音频可用性；不向 renderer 暴露内部文件路径 |
| `getRecordingStatus()` | 查询活动会议、状态、设备、实际采集时长和输入音量 |
| `startRecording(operationId)` | 用 UUID 操作标识开始会议，重复请求保持幂等 |
| `stopRecording(meetingId)` | 请求停止并保存指定会议 |
| `onLifecycleError(listener)` | 接收退出、重连或保存未完成的错误 |

控制协议相应方法为 `health`、`meetings.list`、`meetings.get`、`recording.start/status/stop/interrupt` 和 `shutdown`。会议状态为 `starting`、`recording`、`stopping`、`completed`、`interrupted`、`failed`；没有当前会话时状态查询可返回 `idle`。连接状态独立为 `starting`、`ready`、`error`、`stopped`。

开始请求返回不代表已打开设备，界面需等待真实 `recording` 状态。控制请求超时也不证明业务操作失败：先查询核心状态，不盲目重放开始 / 结束操作。录音能力表示采集依赖和存储初始化可用，具体权限与设备在开始时检查；转写和总结保持不可用。

## 存储与恢复

生产数据根目录来自 Electron `app.getPath('userData')`，独立于项目目录；测试显式设置绝对路径 `PAA_TEST_DATA_DIR` 以隔离数据。目录内部为：

```text
<userData>/
├── meetings.sqlite3
└── meetings/
    └── <UUIDv4>/
        ├── recording.wav    # 录制期间持续写入
        ├── audio.wav        # 正常收尾后的最终音频
        └── recovered.wav    # 中断恢复时另行生成，保留源文件
```

各音频文件按会议状态存在，不保证三个同时存在。SQLite `PRAGMA user_version=1`，单张 `meetings` 表保存 ID、唯一操作标识、标题、带时区时间、状态、时长、错误码、设备、采样率、通道数、采样宽度、帧数、PCM 字节数和相对音频路径。标题按本地时间自动生成。

音频为单声道 PCM16 WAV，采样率由设备参数检查决定。写入更新 WAV 长度并周期性同步磁盘；停止时先关闭采集、排空已接受缓冲、关闭音频，再提交终态元信息。标准 RIFF WAV 有容量上限，不能宣称无限时长。

文件与 SQLite 不共享事务：中间状态和原始文件用于启动恢复。启动时检查未完成会议，依据已落盘的完整 PCM 帧生成可播放恢复文件并标记中断；无有效音频时标记失败。若恢复副本暂时不可写，记录为 `failed` 并保留非空的 `recovered.wav` 恢复目标及已核实帧数；目标关联不代表文件已生成，此时不可播放并提示排除故障后重连。启动同时重试这类待恢复记录，成功后变为 `interrupted`，保留原始文件和失败原因。空 / 无效音频为 `failed` 且无恢复关联。强制终止可能丢失尚在内存中的帧，不承诺零丢失。未知数据库版本、存储不可写、缺失或损坏音频应返回错误，不能删库重建或伪造成功。

## 权限与媒体边界

主进程启用 context isolation、renderer sandbox，关闭 Node integration；校验 IPC 的窗口、主 frame、完整来源 URL 和参数。禁止外部导航、新窗口和 webview，不加载远程脚本。Chromium 权限请求仍默认拒绝，麦克风由 Python 原生采集；macOS 在用户开始时由主进程检查 / 请求麦克风权限，实际可用性仍取决于输入流打开结果。

媒体仅接受会议 UUID 和 GET / HEAD 请求，查询已保存会议后校验固定目录、允许的文件名、实际路径和音频长度，拒绝目录越界与符号链接访问。播放支持字节范围请求以供拖动进度，不把任意 `file://` 或磁盘路径交给页面。录音期间停止既有播放并禁止新的回放。

Spec 001 曾验证额外注入脚本跳转 `about:blank` 可绕过 Electron 的 `will-navigate` 事件而清空界面；当前产品无此入口，空白来源的 IPC 被完整 URL 校验拒绝。导航拦截不是唯一权限边界。

## 进程与生命周期

主进程无 shell 启动 Python，处理含空格路径。开发时优先显式 `PAA_PYTHON`，其次项目 `.venv`，再尝试平台解释器；Python 基线为 3.12，不写入开发机绝对路径。核心缺失或存储失败时窗口仍可出现并显示可理解的错误。

控制消息为带请求 ID 的 UTF-8 JSON Lines；解析、待处理请求数和等待时间有界。协议处理不等待整场录音或磁盘收尾，客户端处理分片行、非法输出、超时与子进程退出。无本地业务 HTTP 服务，Vite 开发服务只绑定本机，构建预览加载本地资源。

最小化和页面切换不停止采集。正常关闭、应用退出或重连先查询活动会议，让用户选择继续录音或停止并保存；保存未完成时保持窗口可见。系统休眠请求中断保存，强制结束后的遗留数据由重启恢复处理。不能直接沿用 Spec 001 的短时强杀退出路径处理活动录音。

## 依赖与后续边界

- Electron / React / TypeScript / electron-vite 沿用 [决策 0004](../.ai/decisions/0004-foundation-stack.md)，具体版本见技术栈及锁文件。
- 录音采用 sounddevice 0.5.6，运行依赖 CFFI 2.1.1、pycparser 3.0，不引入 NumPy。SQLite 和 WAV 使用 Python 3.12 标准库，依据见 [决策 0006](../.ai/decisions/0006-recording-and-storage-baseline.md)。
- ASR 后续接收音频块与采样元信息，输出带相对时间的转写片段；当前不下载 Whisper 模型或承诺实时性能。
- LLM 后续接收完整转写并输出经过验证的会议纪要；服务商、费用、密钥和文本外发规则待对应 Spec 确认。
- TranscriptSegment、MeetingSummary、ActionItem 和 Memory 仍是后续设计边界，本次不建相关表。ASR / LLM 工作不能进入录音回调或 UI 主线程。
- FastAPI、PostgreSQL、pgvector、LangGraph 继续延期，不因最初候选清单而安装。

保留 Spec 001 的后续最小数据约定，不代表本次已建表或提供相关功能：

| 对象 | 预留信息 |
| --- | --- |
| AudioChunk | ID、meeting_id、会议内起止偏移、音频位置与采样元信息 |
| TranscriptSegment | ID、meeting_id、start_time、end_time、text、可空 speaker / confidence |
| MeetingSummary | title、summary、topics、decisions、action_items、risks、open_questions |
| ActionItem | task、可空 owner / deadline、status；不凭空补全未知归属与日期 |

墙上时间带时区，片段时间相对会议开始，ID 保持稳定并能追溯原始音频。未来结束会议后先处理剩余转写再生成纪要，ASR 和总结失败分别记录。

## 平台和分发

目标为 macOS 与 Windows，当前实机开发平台为 macOS ARM64。Windows 的 CI 定义和路径检查不等于 Windows 实机录音验证；结果分别记录。当前不承诺最低系统版本。

本次仍是开发交付，构建预览不包含内嵌 Python、签名、公证、安装包和自动更新。正式分发必须遵循 [决策 0005](../.ai/decisions/0005-self-contained-desktop-distribution.md)：应用自带内部核心及运行时，普通用户无需安装 Python / Node.js 或启动服务。安装包资源路径和无预装运行时环境的验证留给后续分发 Spec。
