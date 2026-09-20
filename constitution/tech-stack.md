# 技术栈与工程约束

本文记录实际技术、目录及运行边界。需求与状态见 [Spec 索引](../specs/README.md)，选型理由见 `.ai/decisions/`；[README](../README.md) 提供使用入口，详细安装／部署／备份步骤集中在[使用指南](../docs/setup.md)。版本以对应锁文件为准。

## 桌面技术基线

| 范围 | 当前选择 |
| --- | --- |
| 平台 | macOS／Windows；当前实机为 macOS ARM64，最低系统版本未承诺 |
| 工具链 | Node 24、npm 11、`package-lock.json`；`npm ci` 的 postinstall 准备 Electron，首次需要网络 |
| 桌面与界面 | Electron 44.3.0、React 19.2.8、TypeScript 5.9.3、CSS；renderer 内存导航，浅／深／系统语义主题 |
| 构建 | electron-vite 5.0.0、Vite 7.3.6、React 插件 5.2.0 |
| 核心与通信 | Python 3.12、venv／pip、`apps/desktop/core/requirements.lock`；main 管理无 shell 子进程，以带请求 ID 的 UTF-8 JSON Lines／stdio 控制 |
| 录音 | sounddevice 0.5.6、CFFI 2.1.1、pycparser 3.0；RawInputStream → 有界队列 → 写盘，不在回调调用数据库／ASR |
| 存储 | SQLite schema 9＋单声道 PCM16 WAV；增量迁移前备份，可恢复删除意图，候选转写完成后原子发布 |
| ASR | 六款 Whisper 多语言模型，默认 small／中文；可用 GPU 优先。CPU：faster-whisper 1.2.1／CTranslate2 4.8.2、INT8、4 线程／beam 5；Windows NVIDIA：CUDA FP16／beam 5；Apple Silicon：mlx-whisper 0.4.3／MLX 0.32.2、Metal FP16／greedy；受管 spawn worker，全局一次推理 |
| LLM | httpx 0.28.1、OpenAI 兼容 Chat Completions；单后台网络 worker，可选 SSE，不自动重试付费请求 |
| 说话人 | Community-1／pyannote.audio 4.0.7，本地 CPU／Apple MPS／可用 CUDA；WeSpeaker 提取及匹配已同步的公司声纹，录音中有界分窗、会后全量校正，保留人工更正；固定权重随核心打包，SHA256 校验，署名与许可随包分发 |
| 模型设置 | main 多服务管理，safeStorage 加密 Key；按服务／模型保存自定义强度或受限 JSON，不硬编码厂商档位 |
| 分发 | electron-builder 26.15.3＋PyInstaller 6.22.2 onedir；macOS ARM64 DMG／Windows x64 NSIS 测试包，签名／公证未纳入 |
| 检查 | Vitest 4.1.11、Python unittest、Playwright 1.63.0、TypeScript、ESLint 9.39.5、Prettier 3.9.6 |

正式包只启动自身资源中的核心，用户无需安装 Python／Node 或手动启服务；开发模式优先项目 `.venv`，可用 `PAA_PYTHON` 指定解释器路径（不能包含 shell 命令），不修改系统 Python。运行时缺失仍可显示故障和重试。依据见 [0004](../.ai/decisions/0004-foundation-stack.md)、[0005](../.ai/decisions/0005-self-contained-desktop-distribution.md)。

## 公司 Web 与服务端基线

| 范围 | 当前选择 |
| --- | --- |
| Web | 现有 React／TypeScript／Vite；React Router 7.18.3 data router 支持草稿离开保护；独立输出 `apps/web/out/` |
| 服务 | Python 3.12、FastAPI 0.141.1、Uvicorn 0.52.4；独立 `.venv-server`、`services/company/requirements.in`／`.lock` |
| 数据 | PostgreSQL 17、SQLAlchemy 2.0.52 async、psycopg 3.3.5、Alembic 1.20.0；schema `0012_member_deletion`，业务数据、私有附件、公司身份、可恢复业务操作及声纹模板 |
| 登录 | 账号密码与可选钉钉企业内部应用 OAuth；本地成员、角色、8 小时会话与 CSRF；桌面经系统浏览器确认及一次性 PKCE 授权，受限令牌依附原 Web 会话；自动开户仅限已核验的公司员工 |
| Harness | Deep Agents 0.7.13、LangGraph 1.2.11、checkpoint-postgres 3.1.2、langchain-openai 1.6.2；按角色授权的业务工具、独立语义意图校验、版本化来源与持久操作回执，提交／删除需确认 |
| 模型 | 受控 ChatOpenAI／httpx 适配聊天；文件转写与 Qwen-ASR 为独立协议；cryptography 50.0.1 AES-GCM 加密公司 Key |
| 媒体 | Pillow＋pillow-heif 校验／规范图片，FFmpeg 处理有界短语音（含 MP3）；外部图文／ASR API，不在服务端部署 faster-whisper |
| 声纹登记 | 可选独立 CPU 环境，管理员上传单人录音，worker 一次提取一份；共享 WeSpeaker 模型／规范版本，原件私有保存，模板仅管理员同步 |
| 文档 | pypdf、python-docx、python-pptx、openpyxl 与标准库；受管子进程提取原生文字／可见表格，不做 OCR；原件在私有卷，分段及定位在 PostgreSQL；Web 用本地 PDF.js 预览原页 |
| 部署 | Linux Docker Compose＋Caddy、API、单 worker 进程、PostgreSQL；支持域名自动 HTTPS 或公网 IPv4 外部证书＋Certbot 续期；任务有界并发，默认 3、可配 1～8，同一成员串行；聊天／ASR 模型外置，声纹提取在 worker，服务器容量待实测 |

公司 API 独立于桌面 stdio；Web 不依赖 `window.paa`。各端同仓库、独立构建／部署，不自动同步 Electron 资料。Web 与 Electron 共用 `packages/ui-web/` 的主题与选择控件 CSS，按各自设备能力组织导航；不能只共用颜色而偏离实际桌面视觉。技术理由与协议边界见 [0011](../.ai/decisions/0011-company-agent-direction.md)、[0012](../.ai/decisions/0012-company-model-services.md) 及其 Plan。

## 目录约定

| 内容 | 位置 |
| --- | --- |
| Electron main／preload、React、桌面契约 | `apps/desktop/src/{main,preload,renderer,shared}/` |
| 本地 Python 核心、依赖锁与构建元数据 | `apps/desktop/core/`；包为 `src/paa_core/` |
| 公司 Web | `apps/web/`；`src/app` 装配、`pages` 路由组合、`features` 业务，公共 API／组件／Hook 分层，见[前端结构](../docs/architecture.md#web-前端组织) |
| 公司 API、任务与 harness | `services/company/src/paa_server/` |
| 公司 HTTP 类型、纯模型参数校验、浏览器 CSS | `packages/api-contracts/`、`packages/model-config/`、`packages/ui-web/` |
| 桌面／公司共用声纹提取与匹配 | `packages/voiceprint-engine/`，轻量协议与可选模型运行依赖分离 |
| 测试 | `tests/{desktop,core,web,server}/`、`tests/e2e/desktop/` |
| 工程脚本、公司部署 | `scripts/{desktop,company,benchmarks,lib}/`、`deploy/company/` |
| 产品／架构、规格、决策／规则／交接 | `docs/`、`specs/`、`.ai/` |

目录按用户确认的 [Spec 015](../specs/spec-015-monorepo-structure/spec.md) 迁移；当前实施／验收状态以该 Spec 为准。Node 应用与共享包由 npm workspaces 管理，一个根 package-lock；各包显式声明依赖，共享包不反向依赖应用。Python 继续使用独立环境。`AGENTS.md`、`constitution/`、`specs/`、`.ai/` 的位置与职责不变，后续不任意建立重复结构。取舍见 [0015](../.ai/decisions/0015-multi-client-repository.md)。

应用构建输出位于各自 `apps/*/out/`，发行包仍在根 `dist/desktop/`，冻结核心在 `dist/core/`。未来移动项目按技术选择放在 apps 下；本轮未创建移动 App，也未承诺原生界面能直接使用浏览器 CSS。

## 工程命令

| 操作 | 命令 |
| --- | --- |
| 桌面开发／构建／预览 | `npm run dev`／`npm run build`／`npm start` |
| 桌面 Python 依赖 | 在仓库根用 Python 3.12 建立 `.venv`，执行 `node scripts/desktop/install-python.mjs` |
| 公司开发 | `npm run dev:company` 启动 Web 5174、API 8000、worker；各自也有 `dev:web`、`dev:server`、`dev:worker` |
| 公司初始化 | `npm run db:company` 迁移；`npm run admin:company` 交互创建首位管理员 |
| 公司声纹运行依赖 | `python3.12 scripts/company/install-voiceprints.py`（Windows 用 `py -3.12`） |
| 桌面定向检查入口 | `npm test`（unit＋Python）、`npm run typecheck`、`npm run lint`、`npm run format:check` |
| 公司定向检查入口 | `npm run test:server`、`npm run test:web`、`npm run typecheck:web`、`npm run build:web` |
| 手动／发布前 | `test:asr`、`test:smoke`、`test:smoke:quick`、`test:smoke:asr`；构建依赖准备后 `package`／`test:package` |

命令是可用入口，不代表每次任务必跑。按 AGENTS.md 的 S0～S3 选择最小必要范围，源码仅格式化本次文件。CI 触发与检查范围以 [CI 工作流](../.github/workflows/ci.yml) 为准，不因新增 Spec 叠加重检查。

## 数据与安全边界

- 桌面 userData 下保存 `meetings.sqlite3`、`meetings/<UUIDv4>/` 音频、`models/` 和加密 `model-services.json`；路径相对存储，stdio 不传整场音频。录音与推理解耦、音频持续写盘，积压由磁盘和检查点承接。
- ASR 模型由用户发起下载，固定 revision／SHA256，就绪后只读本地，无云回退；任务锁定模型、语言与推理设备，默认设置不改变历史任务。Apple GPU 使用独立 MLX 权重目录，CPU 与 NVIDIA GPU 共用 CTranslate2 权重；已测 CPU 错误率／内存不作为 GPU 指标。模型清单、候选发布与 CPU 三语言实测见 [Spec 013](../specs/spec-013-local-model-library/spec.md)，设备策略见 [0007](../.ai/decisions/0007-local-transcription-baseline.md)。纪要任务固定完整文字、所用发言人信息及配置快照，失败保留旧结果；输入变更后由用户手动更新，纯文本模式不因姓名变化失效。新纪要为 version 2，兼容历史 version 1，凭证不入业务数据库。
- 页面导航不改变桌面 renderer URL／IPC 信任边界；会议页签共享唯一播放器，服务编辑器保留草稿。`paa.appearance.theme` 仅存外观偏好，不存 Key。
- 桌面公司连接可选，游客模式无需公司 API；地址使用部署者的 Web 根地址。main 用 safeStorage 保存凭证与公司声纹，按服务／公司／账号隔离，模板不进入 renderer；缓存长期离线可用，断网或令牌过期不清除，主动退出／清缓存才删除。声纹匹配只标记发言，不授予权限。
- 本机桌面验收直接 `npm run dev` 使用默认日常资料。自动故障测试继续使用临时数据，不能让含清理或故障注入的测试操作用户资料；不为 GUI 验收设置隔离 userData。
- 公司配置来自忽略的 `.env.company` 及数据库。API／worker 共用独立私有主密钥文件，凭证只在服务端短暂解密；数据库与密钥分开备份、配对恢复。旧环境模式仅为升级公司保留，显式导入后不回退。
- 公司出站校验 DNS 并固定连接 IP，保留 TLS 主机验证；工具与任务均受公司／员工权限、输入版本、配置修订及预算约束。完整协议和恢复契约分别见 [Spec 008 Plan](../specs/spec-008-meeting-followup/plan.md)、[Spec 009 Plan](../specs/spec-009-company-model-services/plan.md)。
- 公司聊天通过 PostgreSQL 有界快照与同源 SSE 交付受控反馈；工具和来源仍需完整校验。请求记录保留调用时的服务／模型，实际 Token 与预算估算分离，缺失为未知；见 [Spec 016](../specs/spec-016-web-search-metrics-and-feedback/spec.md)。
- 公司报告采用受控结构化输出、服务端校验和事务保存；周期安排保存版本与生效边界，汇报待办独立于生成结果，站内提醒不调用模型。行为与验证入口见 [Spec 017](../specs/spec-017-report-reliability-and-reminders/spec.md)。
- 密钥、录音、用户下载的模型、数据库和原始公司材料不入 Git；已授权随包分发的固定 Community-1 公共权重保存在 `apps/desktop/resources/models/`、不输出到日志。测试库与开发库分离，自动检查不用真实 Key、会议或麦克风。

## 验证边界

逐项通过、失败、跳过及未执行证据只在 [各 Spec 验收](../specs/README.md) 维护。旧 SHA 的 CI 或物理设备结果不能证明新提交已通过；当前实现存在也不代表生产部署、容量或所有平台已验证。真实文字／周报的后续联调见 [Spec 009](../specs/spec-009-company-model-services/acceptance.md)，其结果不扩展为图片／ASR 或长期业务质量结论。
