# 初始技术架构

状态：Spec 001 骨架已实现并通过独立工程验收。具体依赖版本以 package-lock.json 和 `constitution/tech-stack.md` 的落地记录为准；后续 Provider 与会议数据契约仅为设计边界。

## 职责与数据流

```text
React / TypeScript 界面
    ↓ 限定的 preload API
Electron 主进程
    ↓ JSON Lines 请求 / 响应（stdin / stdout）
Python 本地核心
    ↓ 后续接入边界
Recorder / ASR / Transcript / LLM / Repository
```

| 模块 | 位置 | 职责、输入与输出 |
| --- | --- | --- |
| 桌面主进程 | `src/desktop/` | 管理窗口、应用及 Python 生命周期；接收限定 IPC，返回核心状态和结果 |
| preload | `src/desktop/` | 提供少量类型化 API；不暴露任意 IPC、文件读写或进程执行能力 |
| renderer | `src/renderer/` | 中文工作区、空会议和设置界面；消费真实状态，不直接调用 Node/Python |
| shared | `src/shared/` | 运行状态、能力及请求结果的跨边界类型契约 |
| Python 核心 | `src/python/paa_core/` | 解析控制请求，提供状态、空会议查询和有界退出；日志进入 stderr |
| 测试 | `tests/` | 进程边界失败行为、协议解析、Python 核心及 Electron 启动检查 |

本次只实现实际使用的控制边界，后续 Provider 和业务模型在下文定义设计契约，不生成大量未调用的空类。

桌面向界面公开的契约集中在 `src/shared/contracts.ts`：

| API | 用途 |
| --- | --- |
| `getStatus()` | 获取本地核心连接状态和录音 / 转写 / 总结能力 |
| `retryCore()` | 在清理旧进程后重试核心连接 |
| `listMeetings()` | 查询当前会议列表，明确区分成功空列表与核心错误 |
| `onStatusChanged(listener)` | 订阅状态变化，返回取消订阅函数 |

连接状态为 starting、ready、error、stopped；本次 recording / transcription / summary 的 available 均为 false。核心 ready 只说明控制进程已连接，不代表会议功能可用。

## 通信与生命周期

- 主进程使用无 shell 的异步子进程方式启动 Python，处理含空格的可执行文件和项目路径。
- 优先使用显式 `PAA_PYTHON` 可执行文件路径，其次项目 `.venv`，再使用适合平台的 Python 命令。不把开发机器绝对路径写入代码。
- Python 版本基线为 3.12；缺失或版本不合适返回可理解的核心错误状态，桌面窗口仍显示。
- 一行一个 UTF-8 JSON 控制消息，请求携带 ID；响应保留相同 ID，成功数据与错误互斥。
- 仅允许本次实现的健康 / 状态、会议列表、退出等方法。未知方法、无效 JSON、无效请求结构返回明确错误。
- 客户端需处理分片行、非协议输出、超时、子进程退出、写入失败和重试，不无限积累未完成请求或输出缓冲。
- 退出时终止待处理请求并关闭子进程；重试必须清理旧进程。当前控制消息不传输音频二进制。
- 无本地业务 HTTP 服务。开发用 Vite 服务只绑定本机，生产构建加载本地 UI 资源。

## 桌面与配置边界

启用 context isolation、renderer sandbox，关闭 Node integration。preload 只公开需要的方法，主进程校验请求来源与参数。阻止外部页面导航和新窗口，骨架不申请麦克风或其他设备权限，不加载远程脚本。

macOS 验证发现，额外注入脚本跳转 `about:blank` 属于 Electron 未发出 `will-navigate` 的特殊导航，可清空界面；当前产品没有此入口。空白来源调用 preload API 仍被主进程完整 URL 校验拒绝。导航处理不作为唯一权限边界，也不宣称可以阻止任意已注入脚本改变页面内容。

默认运行不依赖 `.env`、密钥或模型。项目可提供 `.env.example` 说明可选 `PAA_PYTHON`，但不能假定 Electron 自动读取 `.env`；README 必须与实际加载方式一致。用户界面只展示可采取行动的错误信息，详细日志不打印整个环境或敏感请求内容。

相关基础能力依据：[Electron 进程模型](https://www.electronjs.org/docs/latest/tutorial/process-model)、[安全指导](https://www.electronjs.org/docs/latest/tutorial/security)、[Node 子进程](https://nodejs.org/api/child_process.html)。上述约束是本项目实施选择，查阅日期为 2026-09-09。

## 后续会议数据契约

以下是后续业务接入的最小设计，不代表本次创建真实会议表或提供 CRUD API。

| 对象 | 最小信息 |
| --- | --- |
| Meeting | ID、标题、创建时间、状态、开始 / 结束时间、原始数据位置 |
| AudioChunk | ID、meeting_id、会议内起止偏移、音频位置、采样元信息 |
| TranscriptSegment | ID、meeting_id、start_time、end_time、text、可空 speaker / confidence |
| MeetingSummary | title、summary、topics、decisions、action_items、risks、open_questions |
| ActionItem | task、可空 owner / deadline、status；未知归属和日期不凭空补全 |

墙上时间使用带时区时间，片段起止采用相对会议开始的秒数；ID 稳定，片段可追溯到原始音频。音频切块时长在功能接入时配置，不写死在核心。

后续接口职责：

- ASR Provider：输入音频分块及元信息，输出带相对时间的转写片段。
- LLM Provider：输入完整转写和分析配置，输出经过验证的 MeetingSummary。
- Repository：保存和读取会议、片段、总结与原始数据引用。
- Memory：未来通过已保存的事实及实体引用关联历史，不替代原始数据存储。

## 录音和推理的后续设计方向

采集使用独立生产者，先保证音频持续获得与可保留，再由有界队列安排 ASR 消费；长任务不能在 UI、录音回调或控制协议读取路径上同步等待。积压策略以可恢复的本地原始音频为基础，达到磁盘或队列阈值时显式报告，不静默丢弃。

结束会议先停止采集并提交末块，待 ASR 队列收尾后固定完整转写，再进行 LLM 分析。ASR 失败与总结失败独立记录。详细重试、磁盘限额、VAD、性能阈值及超长会议整理策略在对应功能 Spec 中验证。

## 技术选择与延期项

- **Electron / React / TypeScript / electron-vite**：本次落地。选择依据和兼容版本见 [工程基线决策](../.ai/decisions/0004-foundation-stack.md)。
- **Python 3.12 标准库**：本次实现控制核心，使用 venv 隔离和 unittest 验证，无额外运行包。标准库测试依据：[unittest](https://docs.python.org/3/library/unittest.html)。
- **SQLite + 文件**：确定为单机 MVP 的存储起点，本次无业务数据，不创建数据库。相比 PostgreSQL 无需单独服务；如后续检索或团队场景需要再评估迁移。[sqlite3](https://docs.python.org/3/library/sqlite3.html)
- **录音**：sounddevice 是待实测候选，官方列出 macOS / Windows；尚未采集音频或验证设备权限。[官方资料](https://python-sounddevice.readthedocs.io/en/latest/)
- **ASR**：优先评估 faster-whisper / Whisper；模型大小、语言质量和吞吐必须按目标设备验证。CTranslate2 对 CPU、CUDA 等硬件有具体限制，不能把 Windows GPU 方案直接假设为 Mac 加速方案。本次不锁定模型，不下载运行库。[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[硬件支持](https://opennmt.net/CTranslate2/hardware_support.html)
- **LLM**：本次仅确定 Provider 输入输出，服务商、密钥管理、文本外发要求、上下文限制在真实总结功能接入前明确。
- **FastAPI / pgvector / LangGraph**：当前骨架不需要，维持延期；不因最初候选清单而安装。

以上官方资料查阅于 2026-09-09。没有实测证据的候选能力保持待验证，不承诺 ASR 实时性能或模型准确率。

## 平台和分发

当前用 macOS ARM64 做实际开发启动与 Electron smoke；Windows 提供可执行的 CI 验证定义，运行前保持“未验证”。Node 24 / Python 3.12 为开发基线，具体系统版本最低支持范围在分发前确认。

本次构建为开发预览产物，不包含 Python 内嵌发行版、签名、公证、安装包和自动更新。避免以 `npm run build` 成功宣称安装包已经可交付。

正式分发必须满足 [用户无需配置运行环境的约束](../.ai/decisions/0005-self-contained-desktop-distribution.md)：将 Python 核心及所需运行时封装为内部程序，随 Electron 应用一起安装，由主进程自动启动与退出。最终应用从自身资源目录定位内部程序，不能依赖目标机器的系统 Python、开发仓库或 `.venv`。这些分发路径与产物尚未实现；后续须在没有预装 Python / Node.js 的目标环境中验证。
