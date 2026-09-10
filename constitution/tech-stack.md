# 技术栈与工程约束

## 当前状态

项目已完成 [Spec 001](../specs/spec-001-product-and-technical-foundation/spec.md)，具有 Electron 桌面入口、React 界面与 Python 本地核心，[独立工程验收](../specs/spec-001-product-and-technical-foundation/acceptance.md) 为 PASS。桌面工程选择来自 [决策 0004](../.ai/decisions/0004-foundation-stack.md)，版本已核对 package-lock.json。LLM 尚未接入。

[Spec 002](../specs/spec-002-meeting-recording-and-storage/spec.md) 已实现 sounddevice 原始输入流、WAV 文件与 SQLite 会议持久化，见 [决策 0006](../.ai/decisions/0006-recording-and-storage-baseline.md)。下方记录当前代码与依赖选择；恢复重试问题已闭环，新的独立工程验收为 [PASS](../specs/spec-002-meeting-recording-and-storage/acceptance.md)。

[Spec 003](../specs/spec-003-local-transcription/spec.md) 代码已实现，正在完成工程验收。一个 faster-whisper Provider 提供本地持续转写，默认 small 多语言模型、CPU / INT8，应用内提示下载；依据见 [决策 0007](../.ai/decisions/0007-local-transcription-baseline.md)。下表记录实际实现；最终验收和平台结果单独留痕。

## 技术基线

| 范围 | 选择 |
| --- | --- |
| 目标平台 | macOS / Windows；当前实机为 macOS ARM64 |
| 桌面 | Electron 44.3.0 |
| 界面 | React 19.2.8、TypeScript 5.9.3、CSS |
| 构建 | electron-vite 5.0.0、Vite 7.3.6、React 插件 5.2.0，满足兼容 peer 范围 |
| Node 工具链 | Node 24、npm 11、package-lock.json；通过 npm ci 复现 |
| Python | Python 3.12、venv + pip；`requirements.lock` 固定运行依赖 |
| 录音 | sounddevice 0.5.6、CFFI 2.1.1、pycparser 3.0；RawInputStream；录音回调不调用 NumPy / ASR |
| 存储 | Python 标准库 SQLite + 单声道 PCM16 WAV，schema version 2，增量保留旧会议 |
| 通信 | Electron 主进程管理 Python 子进程，通过带请求 ID 的 JSON Lines / stdio 通信 |
| 本次核心 | 会议采集、持久化、回放、受控模型准备、持续转写、历史补转写和恢复；不实现 LLM |
| ASR | faster-whisper 1.2.1、CTranslate2 4.8.2；Whisper small，CPU INT8 / 4 线程 / beam 5；完整依赖见 requirements.lock |
| 测试 | Vitest 4.1.11、Python unittest、Playwright 1.63.0 Electron smoke |
| 质量 | TypeScript、ESLint 9.39.5、Prettier 3.9.6、构建检查 |
| 分发 | 开发启动与构建预览；本次不制作签名安装包或内嵌 Python |

正式用户分发约束：应用自带所需运行时与内部处理程序，用户无需安装 Python / Node.js、创建 `.venv` 或手动启动核心。当前解释器选择逻辑仅为开发启动实现，正式安装包与资源路径适配尚未落地。详见 [决策 0005](../.ai/decisions/0005-self-contained-desktop-distribution.md)。

Node / Electron / Python 各自的运行边界、接口与退出行为见 [架构](../docs/architecture.md)。本机系统 Python 3.9 不作为项目基线；可用 Python 3.12 创建 `.venv`，不修改系统解释器。

## 目录约定

| 内容 | 位置 |
| --- | --- |
| 桌面主进程、preload、子进程客户端 | `src/desktop/` |
| React 界面 | `src/renderer/` |
| TS 共享契约 | `src/shared/` |
| Python 核心 | `src/python/paa_core/` |
| 测试 | `tests/` |
| 工程辅助脚本 | `scripts/` |
| 产品与技术文档 | `docs/` |
| Spec、实施与验收报告 | `specs/` |
| 决策、工作流、交接、规则 | `.ai/` |

已有 `src/`、`tests/`、`docs/` 与固定 Agent 结构保持不变。上述是内部扩展，业务代码不移到其他根目录。

## 工程命令

下列命令已在 package.json 配置；验证结果以实施 / 验收报告为准。`npm ci` 的 postinstall 显式准备 Electron 二进制，首次需要网络。

| 操作 | 命令 |
| --- | --- |
| Node 依赖 | `npm ci` |
| Python 环境 | 使用 Python 3.12 创建 `.venv` 后执行 `node scripts/install-python.mjs`，使用项目解释器安装 `requirements.lock`；各平台命令见 README |
| 开发启动 | `npm run dev` |
| 构建与预览 | `npm run build`、`npm start` |
| 单元与协议测试 | `npm test` |
| 真实模型集成 | `npm run test:asr`；首次联网准备固定公开音频和模型，worker 禁止联网推理 |
| Electron 冒烟测试 | `npm run test:smoke` |
| 类型检查 | `npm run typecheck` |
| 静态检查 | `npm run lint` |
| 格式检查 | `npm run format:check` |

## 配置与数据

- `PAA_PYTHON`：可选的 Python 可执行文件路径，不能包含任意 shell 命令。
- 默认优先项目 `.venv`，再使用平台适合的解释器命令；代码不写入开发机路径。
- 窗口在 Python 缺失时仍可打开并显示真实连接错误。
- 不要求 `.env`、LLM 密钥、模型文件或麦克风权限才能启动。
- 数据根目录使用 Electron `app.getPath('userData')`，数据库为 `meetings.sqlite3`，WAV 位于 `meetings/<UUIDv4>/`。测试通过 `PAA_TEST_DATA_DIR` 隔离，不能覆盖用户数据。
- 模型存储于数据根目录的 `models/`，固定 revision / SHA256，用户显式下载后可离线转写。任务、块和片段存于 SQLite；单页最多 50 段。
- 原始会议音频、转写、数据库和模型不进入版本库。
- 不运行本地业务 HTTP 服务或云服务，不输出整个环境变量或凭证。

## 后续能力方向

- SQLite + 原始数据文件在 Spec 002 接入，后续数据扩展需独立设计 schema 迁移。
- Spec 003 使用受管 spawn 工作进程、约 10 秒业务块和最多前后各 4 秒上下文，按静音边界分块；任务锁定配置，已处理位置与文字事务提交。具体模型 revision、文件清单与实测参数见决策 0007 和实施报告。
- LLM 服务商、模型、密钥存储、文本外发规则在真实分析功能接入前确定。
- FastAPI、PostgreSQL、pgvector、LangGraph 当前不引入；是否需要由后续实际需求决定。
- 录音独立于 ASR / LLM，分块策略可配置；后台推理不进入 renderer 或录音回调。

## 验证边界

Spec 001 的 macOS ARM64 基线已通过类型、Lint、格式、构建、16 项 TypeScript 测试、7 项 Python 测试及 3 项真实 Electron 冒烟测试；开发启动与构建预览已实测。验证环境为 Node 24.20.0、npm 11.19.0、Python 3.12.14，详见 [实施报告](../specs/spec-001-product-and-technical-foundation/implementation.md)。

Spec 002 已在默认 MacBook Pro 麦克风完成单声道 PCM16 / 48000 Hz 真实录音（210944 帧、约 4.395 秒），保存后重启可查询并播放。当前有效检查包括返工后的 13 项录音 / 存储回归，未变化区域复用首轮 7 项协议、19 项 TypeScript、6 项 Electron 及类型 / 定向 lint / 构建证据。真实音频、合成故障及执行边界分别记录在 [实施报告](../specs/spec-002-meeting-recording-and-storage/implementation.md)、[返工报告](../specs/spec-002-meeting-recording-and-storage/implementation-rework-1.md) 和 [PASS 验收报告](../specs/spec-002-meeting-recording-and-storage/acceptance.md)。首次 macOS 授权弹框尚未实测。

现有代码 `b9e0e74` 的 [macOS / Windows CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34441992551) 已通过；本机 6 项 Electron 冒烟通过，Windows 运行其中 2 项并跳过 4 项平台受限场景。Windows 实机录音仍未验证；上述旧提交的结果不能代替 Spec 003 的新推理验证。当前不承诺最低系统版本或安装包。

Spec 003 本机证据已包括 31 项 Python、19 项 TypeScript、真实 spawn ASR 和新增 Electron 转写流程；固定 121.76 秒真人中文分块 CER 6.52%，累计推理 44.659 秒。实际麦克风首段延迟、双平台对应提交和独立验收仍在收尾，不能提前标记完成。证据与具体限制见 [实施报告](../specs/spec-003-local-transcription/implementation.md)。
