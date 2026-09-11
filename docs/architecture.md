# 技术架构

状态：Spec 003 已完成本地转写，[独立工程验收](../specs/spec-003-local-transcription/acceptance.md) PASS，实际 macOS / Windows CI 均通过。本文记录当前接口与存储实现，实录证据和平台限制见 [验证记录](../specs/spec-003-local-transcription/verification.md)。Spec 002 的录音、保存与回放基础保留。

## 职责与数据流

```text
React / TypeScript 界面
    ↓ 类型化 preload API
Electron 主进程
    ↓ JSON Lines 控制 / 状态（stdin / stdout）
Python 本地核心
    ├─ 默认麦克风 → RawInputStream → 有界缓冲 → WAV 文件
    ├─ ModelManager → 用户触发的受控下载 / 校验 / 本地模型
    ├─ WAV 已写帧 → 调度器 → 有界音频窗 → spawn ASR worker
    └─ Repository / TranscriptStore → SQLite 会议、任务、块和文字

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
| 转写 | `src/python/paa_core/asr_worker.py`、`transcription.py` | 本地 Provider、受管工作进程、有限上下文和任务优先级 |
| 模型与文字 | `src/python/paa_core/model_manager.py`、`transcript_store.py` | 受控模型准备、事务检查点和文字分页 |
| 模型服务 | `src/desktop/summary-settings.ts`、`src/python/paa_core/llm_provider.py` | 系统加密多服务设置、模型发现及有界 HTTP / SSE |
| 会议纪要 | `src/python/paa_core/meeting_summary.py`、`summary_store.py` | 完整转写快照、单网络 worker、校验与独立成功结果 |
| 核心协议 | `src/python/paa_core/protocol.py` | 控制请求与响应，日志使用 stderr |

录音回调只复制有界音频块并更新顺序信息，文件写入在工作线程完成。音频不经过 JSON 控制协议，不在 renderer 中采集。ASR 模型加载、VAD 和推理运行在独立进程；原始 WAV 与 SQLite 进度承接积压，不积累整场 PCM。输入队列积压、设备中断或写入失败必须显式结束并报告。

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
| `getTranscriptionModel()` / `downloadTranscriptionModel()` / `cancelModelDownload()` | 固定模型状态和受控下载，不接受 URL 或目标路径 |
| `startTranscription(meetingId)` / `getTranscriptionStatus(meetingId)` | 幂等开始或继续、进度与独立任务状态 |
| `listTranscript(meetingId, cursor)` | 每页最多 50 段，不轮询整场文字 |
| `listModelServices()` / `getModelService(id)` / `saveModelService(draft)` / `removeModelService(id)` | 有界多服务设置，不返回密钥 |
| `selectModelService(id)` / `setAutomaticSummary(value)` | 明确选择纪要接收方及自动生成开关 |
| `requestModels(draft)` / `checkModel(draft)` / `getModelOperation(id, offset)` | 使用草稿发起后台请求，按操作 ID 轮询，目录每页 50 条 |
| `getSummary(id)` / `generateSummary(id)` / `getSummarySource(id, segmentId)` | 当前尝试、成功纪要及真实原文片段 |
| `onLifecycleError(listener)` | 接收退出、重连或保存未完成的错误 |

控制协议相应方法为 `health`、`meetings.list`、`meetings.get`、`recording.start/status/stop/interrupt`、`model.status/download/cancel`、`transcription.start/status/activity/pause`、`transcript.list` 和 `shutdown`。会议状态为 `starting`、`recording`、`stopping`、`completed`、`interrupted`、`failed`；没有当前会话时状态查询可返回 `idle`。连接状态独立为 `starting`、`ready`、`error`、`stopped`。

开始请求返回不代表已打开设备，界面需等待真实 `recording` 状态。控制请求超时也不证明业务操作失败：先查询核心状态，不盲目重放开始 / 结束操作。录音能力表示采集依赖和存储初始化可用，具体权限与设备在开始时检查；模型就绪后转写可用，具体会议的处理状态仍独立；纪要能力表示已选择并解锁配置；实际模型权限需通过生成检测确认。

## 存储与恢复

生产数据根目录来自 Electron `app.getPath('userData')`，独立于项目目录；测试显式设置绝对路径 `PAA_TEST_DATA_DIR` 以隔离数据。目录内部为：

```text
<userData>/
├── meetings.sqlite3
├── meetings.schema1.backup.sqlite3  # 如从 schema 1 升级
├── meetings.schema2.backup.sqlite3  # 如从 schema 2 升级
├── meetings.schema3.backup.sqlite3  # 如从 schema 3 升级，新增暂停录音状态语义
├── model-services.json             # 服务与模型预设、系统保护的密钥密文
├── models/                         # 受控模型与临时下载目录
└── meetings/
    └── <UUIDv4>/
        ├── recording.wav    # 录制期间持续写入
        ├── audio.wav        # 正常收尾后的最终音频
        └── recovered.wav    # 中断恢复时另行生成，保留源文件
```

各音频文件按会议状态存在，不保证三个同时存在。SQLite `PRAGMA user_version=4`，保留原有 `meetings` 表，保存 ID、唯一操作标识、标题、带时区时间、状态、时长、错误码、设备、采样率、通道数、采样宽度、帧数、PCM 字节数和相对音频路径。标题按本地时间自动生成。新增转写任务、音频块和片段表；块完成位置与片段在同一事务提交，稳定 ID / 唯一约束防重。迁移前经 staging 生成完整备份；DDL 失败回滚，数据库忙等待有界。旧会议保持未转写，不在升级时自动推理。

音频为单声道 PCM16 WAV，采样率由设备参数检查决定。写入更新 WAV 长度并周期性同步磁盘；停止时先关闭采集、排空已接受缓冲、关闭音频，再提交终态元信息。标准 RIFF WAV 有容量上限，不能宣称无限时长。

文件与 SQLite 不共享事务：中间状态和原始文件用于启动恢复。启动时检查未完成会议，依据已落盘的完整 PCM 帧生成可播放恢复文件并标记中断；无有效音频时标记失败。若恢复副本暂时不可写，记录为 `failed` 并保留非空的 `recovered.wav` 恢复目标及已核实帧数；目标关联不代表文件已生成，此时不可播放并提示排除故障后重连。启动同时重试这类待恢复记录，成功后变为 `interrupted`，保留原始文件和失败原因。空 / 无效音频为 `failed` 且无恢复关联。强制终止可能丢失尚在内存中的帧，不承诺零丢失。未知数据库版本、存储不可写、缺失或损坏音频应返回错误，不能删库重建或伪造成功。

## 权限与媒体边界

主进程启用 context isolation、renderer sandbox，关闭 Node integration；校验 IPC 的窗口、主 frame、完整来源 URL 和参数。禁止外部导航、新窗口和 webview，不加载远程脚本。Chromium 权限请求仍默认拒绝，麦克风由 Python 原生采集；macOS 在用户开始时由主进程检查 / 请求麦克风权限，实际可用性仍取决于输入流打开结果。

媒体仅接受会议 UUID 和 GET / HEAD 请求，查询已保存会议后校验固定目录、允许的文件名、实际路径和音频长度，拒绝目录越界与符号链接访问。播放支持字节范围请求以供拖动进度，不把任意 `file://` 或磁盘路径交给页面。录音期间停止既有播放并禁止新的回放。

Spec 001 曾验证额外注入脚本跳转 `about:blank` 可绕过 Electron 的 `will-navigate` 事件而清空界面；当前产品无此入口，空白来源的 IPC 被完整 URL 校验拒绝。导航拦截不是唯一权限边界。

## 进程与生命周期

主进程无 shell 启动 Python，处理含空格路径。开发时优先显式 `PAA_PYTHON`，其次项目 `.venv`，再尝试平台解释器；Python 基线为 3.12，不写入开发机绝对路径。核心缺失或存储失败时窗口仍可出现并显示可理解的错误。

控制消息为带请求 ID 的 UTF-8 JSON Lines；解析、待处理请求数和等待时间有界。协议处理不等待整场录音或磁盘收尾，客户端处理分片行、非法输出、超时与子进程退出。无本地业务 HTTP 服务，Vite 开发服务只绑定本机，构建预览加载本地资源。

最小化和页面切换不停止采集。正常关闭、应用退出或重连先查询活动会议，让用户选择继续录音或停止并保存；保存未完成时保持窗口可见。系统休眠请求中断保存，强制结束后的遗留数据由重启恢复处理。不能直接沿用 Spec 001 的短时强杀退出路径处理活动录音。仅转写活动时可选择继续处理或保留进度退出；不等待整场推理。启动先恢复录音，再把未完成转写置 paused，由用户继续；worker 超时、崩溃或退出须回收，不重启正在录音的核心。

## 本地转写与后续边界

- faster-whisper 1.2.1 / CTranslate2 4.8.2，固定 Systran small revision `536b0662742c02347bc0e980a01041f333bce120`，CPU INT8 / 4 线程 / beam 5；模型约 487 MB。文件校验清单固化于 ModelManager。
- 用户显式下载，HTTPS 固定来源与重定向白名单、真实字节进度、取消与重试。临时目录通过 hash 和实际加载检查后才发布，缺失模型不阻断录音。推理仅加载本地模型，音频与文字不外发。
- 目标块约 10 秒（配置 5～15 秒），在目标前 5 秒内优先选择静音边界，前后最多各 4 秒上下文。VAD 区间分别解码，通过词时间中点决定归属，保留原会议内偏移。
- 全局一次推理，活动录音优先，历史任务在块边界让出。读取已写的完整帧后关闭 WAV 句柄，再执行推理；短读与最终文件重命名互斥，兼顾 Windows 文件占用。
- 任务保存模型与参数、已处理帧数，静音块也推进进度；结束后按最终帧数补尾块。录音状态与转写状态分别显示，缺失音频不能伪造处理完成，中断来源持续标明不完整。
- renderer 有界分页、非重叠轮询，翻看上文时停止自动跟随；已保存片段可定位播放器，录音期间禁播。speaker / confidence 保持空值，不生成说话人身份。
- sounddevice 原始输入流不变；NumPy、PyAV 与 ONNX Runtime 用于实际 ASR / VAD，完整锁定依赖见 `requirements.lock`。SQLite 与 WAV 沿用标准库。
- 本地转写与模型网络 worker 独立；Memory、FastAPI、PostgreSQL、pgvector、LangGraph 继续延期。

墙上时间带时区，片段时间相对累计音频时间（不含暂停），ID 稳定并可追溯原始音频。正式迁移备份和恢复操作见 README；不能用旧程序直接写 schema 4。

## 在线模型与纪要

服务设置由主进程验证后使用异步 safeStorage 加密密钥，原子写入独立文件；修改串行处理，未激活服务不改变核心配置。只有活动服务经受控 stdio 解密传入核心内存，草稿的模型发现和连接检测建立临时上下文。Base URL 仅接受 HTTPS，禁止自动跳转；测试只有显式隔离目录和 `PAA_TEST_ALLOW_HTTP=1` 才允许 loopback HTTP。普通 renderer 无通用网络代理、任意核心方法或密钥读取入口。

统一 Chat Completions 传输，共用草稿检测和纪要生成的请求构造器。推理预设按服务／模型保存，默认省略参数；自定义字符串或嵌套 JSON 经大小、类型、深度和受保护字段校验后发送，不引入厂商型号白名单。模型目录来源于受控 models 请求，百炼官方入口只做同源路径转换。列表权限与生成权限独立；流式模式仅汇总正文，不保存思维链。

转写保存完成事件在核心发起自动尝试，不靠界面轮询。完整有序文字及配置被固定为任务快照，单网络 worker 处理纪要、模型列表和检测，控制循环不等网络。`summary_attempts` 按会议／输入摘要去重，失败不会自动重试；升级和重连不扫描旧会议。更换配置中断尚未发出的旧队列任务，在途请求继续使用原快照。退出有界停止调度，重启将未完成任务标为中断，晚到结果不能覆盖终态。

`summary_jobs` 保存最新尝试状态，`meeting_summaries` 独立保存最后成功结果；重新生成失败不删除旧结果。结果经过结构、字段、长度及真实片段引用校验，UI 按同一结构显示，引用可直接按 ID 读取并复用回放。输入请求上限 256 KiB、服务响应 1 MiB、结构化纪要 48 KiB，控制消息仍限制 64 KiB；超限明确失败，不截断或自动增加调用。详细协议和约束见 [Spec 004 Plan](../specs/spec-004-meeting-minutes/plan.md)。

## 平台和分发

目标为 macOS 与 Windows，当前实机开发平台为 macOS ARM64。Windows 的 CI 定义和路径检查不等于 Windows 实机录音验证；结果分别记录。当前不承诺最低系统版本。

Spec 005 增加 electron-builder + PyInstaller onedir 的测试安装包，macOS ARM64 DMG / Windows x64 NSIS 随包提供 Python 3.12 与原生依赖，暂不做正式签名、公证或自动更新。分发遵循 [决策 0005](../.ai/decisions/0005-self-contained-desktop-distribution.md)：应用自带内部核心及运行时，普通用户无需安装 Python / Node.js 或启动服务。打包模式仅从 `process.resourcesPath/paa-core` 启动冻结程序，忽略开发解释器覆盖；入口先执行 `freeze_support()`，支持 ASR spawn。运行资源位于 ASAR 外，不写入程序目录。实际平台证据见 Spec 005 实施报告。

## 暂停录音与播放

`pauseRecording(meetingId)` / `resumeRecording(meetingId)` 通过受限 IPC 和 JSON Lines 对应 `recording.pause` / `recording.resume`。`pausing`、`paused`、`resuming` 均为活动会议，参与退出保护、恢复、禁止第二场会议和播放限制。控制线程只发起状态变化，录音线程串行关流、排空队列并 fsync 后确认暂停；继续重新打开输入设备，保持同一 WAV 及采样率，旧流回调通过代次拒绝。暂停时帧数与音频时长不增长，不触发转写完成或自动纪要。schema 4 不改变表结构，升级前备份旧数据库并阻止旧版按错误的状态语义恢复。

播放器用一个 HTMLAudioElement 解码，React 控件处理定位、倍速、音量、时间和上下文快捷键；继续使用原有受限 Range 请求，不把整场音频先加载进 renderer。文字和纪要引用调用同一播放器定位入口。
