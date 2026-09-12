# 技术栈与工程约束

## 当前状态

项目已完成 [Spec 001](../specs/spec-001-product-and-technical-foundation/spec.md)，具有 Electron 桌面入口、React 界面与 Python 本地核心，[独立工程验收](../specs/spec-001-product-and-technical-foundation/acceptance.md) 为 PASS。桌面工程选择来自 [决策 0004](../.ai/decisions/0004-foundation-stack.md)，版本已核对 package-lock.json。

[Spec 002](../specs/spec-002-meeting-recording-and-storage/spec.md) 已实现 sounddevice 原始输入流、WAV 文件与 SQLite 会议持久化，见 [决策 0006](../.ai/decisions/0006-recording-and-storage-baseline.md)。下方记录当前代码与依赖选择；恢复重试问题已闭环，新的独立工程验收为 [PASS](../specs/spec-002-meeting-recording-and-storage/acceptance.md)。

[Spec 003](../specs/spec-003-local-transcription/spec.md) 已完成，独立工程验收 [PASS](../specs/spec-003-local-transcription/acceptance.md)。一个 faster-whisper Provider 提供本地持续转写，默认 small 多语言模型、CPU / INT8，应用内提示下载；依据见 [决策 0007](../.ai/decisions/0007-local-transcription-baseline.md)。下表记录实际实现；真实麦克风和最终双平台 CI 证据见文末。

[Spec 004](../specs/spec-004-meeting-minutes/spec.md) 已完成业务实施与必要本地检查，独立复验已关闭发现的工程缺陷。代码已接入多服务 API 设置、自定义推理预设和会后纪要；`9b2dc93` 的双平台 CI 已通过，真实服务样本核对仍待补，详见 [实施报告](../specs/spec-004-meeting-minutes/implementation.md) 与 [验收报告](../specs/spec-004-meeting-minutes/acceptance.md)。

## 技术基线

| 范围 | 选择 |
| --- | --- |
| 目标平台 | macOS / Windows；当前实机为 macOS ARM64 |
| 桌面 | Electron 44.3.0 |
| 界面 | React 19.2.8、TypeScript 5.9.3、CSS |
| 页面与外观 | renderer 内存导航；会议页签共用播放器，服务编辑器保留草稿；语义主题支持浅色、深色和跟随系统，详见 Spec 006 |
| 构建 | electron-vite 5.0.0、Vite 7.3.6、React 插件 5.2.0，满足兼容 peer 范围 |
| Node 工具链 | Node 24、npm 11、package-lock.json；通过 npm ci 复现 |
| Python | Python 3.12、venv + pip；`requirements.lock` 固定运行依赖 |
| 录音 | sounddevice 0.5.6、CFFI 2.1.1、pycparser 3.0；RawInputStream；录音回调不调用 NumPy / ASR |
| 存储 | Python 标准库 SQLite + 单声道 PCM16 WAV，schema version 5；新增可恢复删除意图，先备份再增量升级 |
| 通信 | Electron 主进程管理 Python 子进程，通过带请求 ID 的 JSON Lines / stdio 通信 |
| 当前核心 | 会议采集、持久化、回放、受控模型准备、持续转写、历史补转写和恢复，以及转写完成后的纪要队列 |
| ASR | faster-whisper 1.2.1、CTranslate2 4.8.2；Whisper small，CPU INT8 / 4 线程 / beam 5；完整依赖见 requirements.lock |
| LLM | httpx 调用 OpenAI 兼容 Chat Completions；一个后台网络 worker，支持非流式与显式选择的 SSE；不自动重试付费请求 |
| API 配置 | Electron 主进程管理多个服务；safeStorage 系统加密密钥；每个服务／模型保存自定义强度字符串或受限 JSON 预设 |
| 测试 | Vitest 4.1.11、Python unittest、Playwright 1.63.0 Electron smoke |
| 质量 | TypeScript、ESLint 9.39.5、Prettier 3.9.6、构建检查 |
| 分发 | electron-builder 26.15.3 + PyInstaller 6.22.2 onedir；macOS ARM64 DMG / Windows x64 NSIS 测试包，Spec 005 验收中 |

用户分发约束：应用自带所需运行时与内部处理程序，用户无需安装 Python / Node.js、创建 `.venv` 或手动启动核心。安装模式仅启动随包核心，开发模式保留解释器选择。正式签名／公证不在本轮范围，产物的实际验证边界见 [Spec 005 实施报告](../specs/spec-005-desktop-distribution-and-controls/implementation.md)。

分发实现与录音操作增强的范围见 [Spec 005](../specs/spec-005-desktop-distribution-and-controls/spec.md)，状态 ACCEPTANCE；当前技术基线描述代码事实，尚未验收的能力不作为已交付结果。

Node / Electron / Python 各自的运行边界、接口与退出行为见 [架构](../docs/architecture.md)。本机系统 Python 3.9 不作为项目基线；可用 Python 3.12 创建 `.venv`，不修改系统解释器。

## 目录约定

| 内容 | 位置 |
| --- | --- |
| 桌面主进程、preload、子进程客户端 | `src/desktop/` |
| Electron React 界面 | `src/renderer/` |
| 公司 Web／共用语义主题 | `src/web/`、`src/ui/theme.css` |
| 公司 API、任务与业务 harness | `src/python/paa_server/` |
| 公司部署 | `deploy/company/` |
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
| 测试安装包 | `node scripts/install-build-python.mjs` 准备构建依赖；`npm run package` 构建当前平台安装包，`npm run test:package` 检查实际资源 |
| 单元与协议测试 | `npm test` |
| 真实模型集成 | `npm run test:asr`；首次联网准备固定公开音频和模型，worker 禁止联网推理 |
| Electron 冒烟测试 | `npm run test:smoke` |
| 受控桌面流程（手动／发布前） | `npm run test:smoke:quick`；真实模型专用入口为 `npm run test:smoke:asr` |
| 类型检查 | `npm run typecheck` |
| 静态检查 | `npm run lint` |
| 格式检查 | `npm run format:check` |

CI 在 PR 上运行双平台单元／模块测试和普通构建，格式、Lint、类型只运行一次；桌面、模型与安装包等重检查通过手动入口或发布标签运行，普通分支推送不触发。具体范围和汇总检查统一见 [README：CI 分层](../README.md#ci-分层)。本地继续按 S0～S3 选择检查，GUI 验收使用用户日常环境。

## 配置与数据

- `PAA_PYTHON`：可选的 Python 可执行文件路径，不能包含任意 shell 命令。
- 默认优先项目 `.venv`，再使用平台适合的解释器命令；代码不写入开发机路径。
- 窗口在 Python 缺失时仍可打开并显示真实连接错误。
- 不要求 `.env`、LLM 密钥、模型文件或麦克风权限才能启动。
- 数据根目录使用 Electron `app.getPath('userData')`，数据库为 `meetings.sqlite3`，WAV 位于 `meetings/<UUIDv4>/`。测试通过 `PAA_TEST_DATA_DIR` 隔离，不能覆盖用户数据。
- 模型存储于数据根目录的 `models/`，固定 revision / SHA256，用户显式下载后可离线转写。任务、块和片段存于 SQLite；单页最多 50 段。
- 服务设置存于数据根目录的 `model-services.json`，密钥仅保存加密值；数据库不存凭证。纪要读取该会议的完整转写，生成任务锁定服务、模型与参数快照，失败保留上一份成功结果。
- 外观选择保存在 renderer 的 `localStorage`，键为 `paa.appearance.theme`；只保存 `system` / `light` / `dark`，不存服务密钥。页面切换不修改 renderer URL 或 IPC 信任边界，界面要求见 [Spec 006](../specs/spec-006-interface-and-navigation/spec.md)。
- Spec 007 的本地检索／导出由有界后台资料 worker 处理；导出先创建私有 SQLite 一致快照，再以 16 KiB 分块交给主进程写入用户所选位置。删除意图在文件清理前持久化，任务写入共享状态保护，失败保留重试入口。完整边界见 [Plan](../specs/spec-007-meeting-library/plan.md)。
- 原始会议音频、转写、数据库和模型不进入版本库。
- Electron 本地核心不监听业务 HTTP；公司 Web 使用独立 API 和数据库。不得输出整个环境变量或凭证，也不自动同步桌面资料。

## 后续能力方向

- SQLite + 原始数据文件在 Spec 002 接入，后续数据扩展需独立设计 schema 迁移。
- Spec 003 使用受管 spawn 工作进程、约 10 秒业务块和最多前后各 4 秒上下文，按静音边界分块；任务锁定配置，已处理位置与文字事务提交。具体模型 revision、文件清单与实测参数见决策 0007 和实施报告。
- Spec 004 的接口、参数边界和密钥存储依据见 [决策 0008](../.ai/decisions/0008-meeting-minutes-provider.md) 与对应 Plan；工程验收及真实服务验证以该 Spec 的报告为准。
- 目标架构采用共享服务端＋多种客户端；首期公司消息与汇报业务优先 Web，Electron 保留现有本地会议能力并在后续按需接入。[决策 0011](../.ai/decisions/0011-company-agent-direction.md) 已确认同仓库、独立入口与部署方案，Spec 008 处于 ACCEPTANCE。
- Web 与 Electron 共用 `src/ui/theme.css`，Web 使用浏览器导航与响应式布局，不依赖 window.paa。完整交互约束见 [Spec 008](../specs/spec-008-meeting-followup/spec.md)。
- 公司业务已新增 FastAPI／PostgreSQL 与实际 Deep Agents 工具流程；保留人工确认、权限和来源边界。真实模型／ASR、手机实机、完整生产部署和小服务器容量尚待外部验证，具体结果统一见 [实施报告](../specs/spec-008-meeting-followup/implementation.md)。
- 录音独立于 ASR / LLM，分块策略可配置；后台推理不进入 renderer 或录音回调。

## 公司 Web 与服务端基线

| 范围 | 当前实现 |
| --- | --- |
| Web | 现有 React／TypeScript／Vite，React Router 7.18.3，独立输出 `out/web/` |
| 服务 | Python 3.12、FastAPI 0.141.1、Uvicorn 0.52.4；独立 `.venv-server` 与 `requirements-server.lock` |
| 数据 | PostgreSQL 17、SQLAlchemy 2.0.52 async、psycopg 3.3.5、Alembic 1.20.0；附件私有存储，独立于桌面 SQLite |
| Harness | Deep Agents 0.7.13、LangGraph 1.2.11、checkpoint-postgres 3.1.2、langchain-openai 1.6.2；固定授权业务工具、持久恢复、人工确认 |
| 媒体 | Pillow 校验图片，FFmpeg 将有界短语音转成 WAV；外部图文／ASR 服务，未引入服务端 faster-whisper |
| 部署 | Linux Docker Compose＋Caddy；API、单并发 worker 和 PostgreSQL；本机数据库与依赖已启动，完整镜像部署尚未验证 |

`npm run dev:company` 同时运行 Web（5174）、API（8000）和 worker；`db:company` 初始化数据库，`admin:company` 交互创建首位管理员。`typecheck:web`、`test:web`、`test:server`、`build:web` 为新模块定向检查。环境准备、模型配置和部署步骤只在 [README](../README.md#公司工作助手-webspec-008) 维护。

部署配置来自忽略的 `.env.company`；公司模型配置及加密凭证入库、仅供服务端使用。开发数据与自动测试库分离；测试不读取 Electron 密钥、会议或模型。新增 CI 模块使用单个 Linux／PostgreSQL 环境，不调用真实模型或麦克风。

[Spec 009](../specs/spec-009-company-model-services/spec.md) 已实施公司模型服务表、不可变配置修订、独立用途分配与任务配置绑定（公司 Alembic schema `0002_model_services`）。API Key 由 `cryptography 50.0.1` AES-GCM 加密，主密钥在独立私有文件；环境配置仅为升级时已有公司保留，显式导入后不回退。ChatOpenAI 子类通过受控 HTTP 适配器处理流式／非流式聊天，文件转写与 Qwen-ASR 为两个独立协议；网络边界检查 DNS 并固定连接 IP。Web 采用同一 React Router 的 data router 以保护包含未保存 Key 的离开操作。依据见 [决策 0012](../.ai/decisions/0012-company-model-services.md)，实现与未验证项见 [实施摘要](../specs/spec-009-company-model-services/implementation.md)，独立工程 [验收通过](../specs/spec-009-company-model-services/acceptance.md)，真实供应商与生产环境仍待验证。

## 验证边界

Spec 001 的 macOS ARM64 基线已通过类型、Lint、格式、构建、16 项 TypeScript 测试、7 项 Python 测试及 3 项真实 Electron 冒烟测试；开发启动与构建预览已实测。验证环境为 Node 24.20.0、npm 11.19.0、Python 3.12.14，详见 [实施报告](../specs/spec-001-product-and-technical-foundation/implementation.md)。

Spec 002 的真实录音、恢复返工和验证范围统一见 [实施摘要](../specs/spec-002-meeting-recording-and-storage/implementation.md) 与 [PASS 验收](../specs/spec-002-meeting-recording-and-storage/acceptance.md)。首次 macOS 授权弹框尚未实测。

现有代码 `b9e0e74` 的 [macOS / Windows CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34441992551) 已通过；本机 6 项 Electron 冒烟通过，Windows 运行其中 2 项并跳过 4 项平台受限场景。Windows 实机录音仍未验证；上述旧提交的结果不能代替 Spec 003 的新推理验证。当前不承诺最低系统版本或安装包。

Spec 003 最终代码 `0b84fe1` 的 [双平台 CI](https://github.com/shi-YangYang/work-assistant-agent/actions/runs/34451673078) 已完整通过：每个平台 19 项 TypeScript、35 项 Python、真实 small 推理及类型 / lint / 格式 / 构建；macOS 7 项 Electron smoke 通过，Windows 3 项通过、4 项既有平台受限场景跳过，新增真实转写未跳过。固定 121.76 秒真人中文分块 CER 6.52%、累计推理 44.659 秒；用户指定的物理声学回采 37.035 秒，首段文字 18.383 秒，保存补尾 / 重启 / 定位回放均完成。独立验收 PASS，原失败、返工、测量边界与未验证事项见 [完整证据](../specs/spec-003-local-transcription/verification.md)。Windows 物理麦克风和正式安装包仍未验证。
