# 技术栈与工程约束

本文记录实际技术、目录及运行边界。需求与状态见 [Spec 索引](../specs/README.md)，选型理由见 `.ai/decisions/`，安装／使用／部署步骤只在 [README](../README.md) 维护；版本以对应锁文件为准。

## 桌面技术基线

| 范围 | 当前选择 |
| --- | --- |
| 平台 | macOS／Windows；当前实机为 macOS ARM64，最低系统版本未承诺 |
| 工具链 | Node 24、npm 11、`package-lock.json`；`npm ci` 的 postinstall 准备 Electron，首次需要网络 |
| 桌面与界面 | Electron 44.3.0、React 19.2.8、TypeScript 5.9.3、CSS；renderer 内存导航，浅／深／系统语义主题 |
| 构建 | electron-vite 5.0.0、Vite 7.3.6、React 插件 5.2.0 |
| 核心与通信 | Python 3.12、venv／pip、`requirements.lock`；main 管理无 shell 子进程，以带请求 ID 的 UTF-8 JSON Lines／stdio 控制 |
| 录音 | sounddevice 0.5.6、CFFI 2.1.1、pycparser 3.0；RawInputStream → 有界队列 → 写盘，不在回调调用数据库／ASR |
| 存储 | SQLite schema 5＋单声道 PCM16 WAV；增量迁移前备份，可恢复删除意图 |
| ASR | faster-whisper 1.2.1、CTranslate2 4.8.2；Whisper small 多语言、CPU INT8，4 线程／beam 5；受管 spawn worker，全局一次推理 |
| LLM | httpx 0.28.1、OpenAI 兼容 Chat Completions；单后台网络 worker，可选 SSE，不自动重试付费请求 |
| 模型设置 | main 多服务管理，safeStorage 加密 Key；按服务／模型保存自定义强度或受限 JSON，不硬编码厂商档位 |
| 分发 | electron-builder 26.15.3＋PyInstaller 6.22.2 onedir；macOS ARM64 DMG／Windows x64 NSIS 测试包，签名／公证未纳入 |
| 检查 | Vitest 4.1.11、Python unittest、Playwright 1.63.0、TypeScript、ESLint 9.39.5、Prettier 3.9.6 |

正式包只启动自身资源中的核心，用户无需安装 Python／Node 或手动启服务；开发模式优先项目 `.venv`，可用 `PAA_PYTHON` 指定解释器路径（不能包含 shell 命令），不修改系统 Python。运行时缺失仍可显示故障和重试。依据见 [0004](../.ai/decisions/0004-foundation-stack.md)、[0005](../.ai/decisions/0005-self-contained-desktop-distribution.md)。

## 公司 Web 与服务端基线

| 范围 | 当前选择 |
| --- | --- |
| Web | 现有 React／TypeScript／Vite；React Router 7.18.3 data router 支持草稿离开保护；独立输出 `out/web/` |
| 服务 | Python 3.12、FastAPI 0.141.1、Uvicorn 0.52.4；独立 `.venv-server`、`requirements-server.in`／`.lock` |
| 数据 | PostgreSQL 17、SQLAlchemy 2.0.52 async、psycopg 3.3.5、Alembic 1.20.0；schema `0002_model_services`，私有附件存储 |
| Harness | Deep Agents 0.7.13、LangGraph 1.2.11、checkpoint-postgres 3.1.2、langchain-openai 1.6.2；固定授权工具、输入与配置版本绑定、持久恢复、人工确认 |
| 模型 | 受控 ChatOpenAI／httpx 适配聊天；文件转写与 Qwen-ASR 为独立协议；cryptography 50.0.1 AES-GCM 加密公司 Key |
| 媒体 | Pillow 校验／规范图片，FFmpeg 处理有界短语音；外部图文／ASR API，不在服务端部署 faster-whisper |
| 部署 | Linux Docker Compose＋Caddy、API、单并发 worker、PostgreSQL；模型推理外置，服务器容量待实测 |

公司 API 独立于桌面 stdio；Web 不依赖 `window.paa`。各端同仓库、独立构建／部署，不自动同步 Electron 资料。Web 与 Electron 共用 `src/ui/theme.css`、`src/ui/select.css`，按各自设备能力组织导航；不能只共用颜色而偏离实际桌面视觉。技术理由与协议边界见 [0011](../.ai/decisions/0011-company-agent-direction.md)、[0012](../.ai/decisions/0012-company-model-services.md) 及其 Plan。

## 目录约定

| 内容 | 位置 |
| --- | --- |
| Electron main／preload、React、桌面契约 | `src/desktop/`、`src/renderer/`、`src/shared/` |
| 本地 Python 核心 | `src/python/paa_core/` |
| 公司 Web、共享纯 UI | `src/web/`、`src/ui/` |
| 公司 API、任务与 harness | `src/python/paa_server/`；HTTP DTO 为 `src/shared/company-contracts.ts` |
| 测试、工程脚本、公司部署 | `tests/`、`scripts/`、`deploy/company/` |
| 产品／架构、规格、决策／规则／交接 | `docs/`、`specs/`、`.ai/` |

保留现有业务根目录及 `AGENTS.md`、`constitution/`、`specs/`、`.ai/` 的职责，不迁移或建立重复结构。

## 工程命令

| 操作 | 命令 |
| --- | --- |
| 桌面开发／构建／预览 | `npm run dev`／`npm run build`／`npm start` |
| 桌面 Python 依赖 | 用 Python 3.12 建立 `.venv`，执行 `node scripts/install-python.mjs` |
| 公司开发 | `npm run dev:company` 启动 Web 5174、API 8000、worker；各自也有 `dev:web`、`dev:server`、`dev:worker` |
| 公司初始化 | `npm run db:company` 迁移；`npm run admin:company` 交互创建首位管理员 |
| 桌面定向检查入口 | `npm test`（unit＋Python）、`npm run typecheck`、`npm run lint`、`npm run format:check` |
| 公司定向检查入口 | `npm run test:server`、`npm run test:web`、`npm run typecheck:web`、`npm run build:web` |
| 手动／发布前 | `test:asr`、`test:smoke`、`test:smoke:quick`、`test:smoke:asr`；构建依赖准备后 `package`／`test:package` |

命令是可用入口，不代表每次任务必跑。按 AGENTS.md 的 S0～S3 选择最小必要范围，源码仅格式化本次文件。CI 触发与分层唯一来源为 [README](../README.md#ci-分层)，不因新增 Spec 叠加重检查。

## 数据与安全边界

- 桌面 userData 下保存 `meetings.sqlite3`、`meetings/<UUIDv4>/` 音频、`models/` 和加密 `model-services.json`；路径相对存储，stdio 不传整场音频。录音与推理解耦、音频持续写盘，积压由磁盘和检查点承接。
- ASR 模型由用户发起下载，固定 revision／SHA256，就绪后只读本地，无云回退；块参数和锁定值见 [Spec 003 验证记录](../specs/spec-003-local-transcription/verification.md)。纪要任务固定完整转写／配置快照，失败保留旧结果，凭证不入业务数据库。
- 页面导航不改变桌面 renderer URL／IPC 信任边界；会议页签共享唯一播放器，服务编辑器保留草稿。`paa.appearance.theme` 仅存外观偏好，不存 Key。
- 本机桌面验收直接 `npm run dev` 使用默认日常资料。自动故障测试继续使用临时数据，不能让含清理或故障注入的测试操作用户资料；不为 GUI 验收设置隔离 userData。
- 公司配置来自忽略的 `.env.company` 及数据库。API／worker 共用独立私有主密钥文件，凭证只在服务端短暂解密；数据库与密钥分开备份、配对恢复。旧环境模式仅为升级公司保留，显式导入后不回退。
- 公司出站校验 DNS 并固定连接 IP，保留 TLS 主机验证；工具与任务均受公司／员工权限、输入版本、配置修订及预算约束。完整协议和恢复契约分别见 [Spec 008 Plan](../specs/spec-008-meeting-followup/plan.md)、[Spec 009 Plan](../specs/spec-009-company-model-services/plan.md)。
- 密钥、录音、模型、数据库和原始公司材料不入 Git、不输出到日志。测试库与开发库分离，自动检查不用真实 Key、会议或麦克风。

## 验证边界

逐项通过、失败、跳过及未执行证据只在 [各 Spec 验收](../specs/README.md) 维护。旧 SHA 的 CI 或物理设备结果不能证明新提交已通过；当前实现存在也不代表生产部署、容量或所有平台已验证。真实文字／周报的后续联调见 [Spec 009](../specs/spec-009-company-model-services/acceptance.md)，其结果不扩展为图片／ASR 或长期业务质量结论。
