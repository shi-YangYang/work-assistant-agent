# 技术栈与工程约束

开发环境：Node.js 24、npm 11、Python 3.12。依赖版本由 `package-lock.json` 和各 Python 锁文件固定。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| Web | React、TypeScript、Vite、React Router、CSS Modules |
| 桌面 | Electron、React、electron-vite；main／preload／renderer 隔离 |
| 桌面核心 | Python、sounddevice、SQLite、PCM16 WAV；JSON Lines／stdio 通信 |
| 本地转写 | faster-whisper／CTranslate2；Apple Silicon 使用 MLX Whisper |
| 说话人与声纹 | pyannote Community-1、WeSpeaker、PyTorch；固定权重及预处理版本 |
| 公司服务端 | FastAPI、Uvicorn、SQLAlchemy async、psycopg、Alembic、PostgreSQL 17 |
| Agent | Deep Agents、LangGraph、PostgreSQL checkpoint；业务工具、来源校验、操作回执和人工确认 |
| 模型接入 | Chat Completions、独立语音协议适配；公司凭证使用 AES-GCM，桌面使用 safeStorage |
| 文档与媒体 | pypdf、python-docx、python-pptx、openpyxl、Pillow／pillow-heif、PDF.js、FFmpeg |
| 部署与打包 | Docker Compose、Caddy；electron-builder、PyInstaller |
| 检查 | Vitest、unittest、pytest、Playwright、TypeScript、ESLint、Prettier |

## 目录约定

| 内容 | 位置 |
| --- | --- |
| 桌面 main／preload／renderer／契约 | `apps/desktop/src/` |
| 桌面 Python 核心与依赖锁 | `apps/desktop/core/`，包名 `paa_core` |
| Web 前端 | `apps/web/src/` |
| 公司 API、worker、harness、迁移 | `apps/server/app/`，包名 `app` |
| 共享 HTTP 类型、模型参数、品牌、声纹引擎 | `packages/{api-contracts,model-config,ui-web,voiceprint-engine}/` |
| 测试 | `tests/{desktop,core,web,server}/`、`tests/e2e/desktop/` |
| 脚本与部署 | `scripts/`、`deploy/company/` |
| 产品方向、架构／使用指南、规格、Agent 规则 | `constitution/`、`docs/`、`specs/`、`.ai/` |

- Node 使用 npm workspaces 和一个根锁文件，各应用声明自身依赖；共享包不反向依赖应用。
- 桌面 `.venv`、公司 `.venv-server` 分开安装；可选公司声纹环境为 `.venv-voiceprints`。
- 公司配置放 `apps/server/.env.web`；桌面配置放 `apps/desktop/.env.electron`，各有同目录示例。真实配置不入 Git。
- 应用配置就近维护；根目录保留 workspace、统一检查和公共 TypeScript 配置。
- 构建输出在各应用的 `out/`；桌面发行包在 `dist/desktop/`，冻结核心在 `dist/core/`。

## 工程命令

| 操作 | 命令 |
| --- | --- |
| 桌面开发／构建／预览 | `npm run dev:electron`／`npm run build`／`npm start` |
| 桌面 Python 依赖 | 创建 `.venv` 后运行 `node scripts/desktop/install-python.mjs` |
| 公司开发 | `npm run dev:web`：Web 5174、API 8000、worker |
| 分别启动前端／API／worker | `npm run dev:web:ui`／`npm run dev:server`／`npm run dev:worker` |
| 数据库迁移／初始化管理员 | `npm run db:company`／`npm run admin:company` |
| 公司声纹依赖 | `python3.12 scripts/company/install-voiceprints.py`；Windows 使用 `py -3.12` |
| 桌面模块检查 | `npm test`、`npm run typecheck` |
| 公司模块检查 | `npm run test:server`、`npm run test:web`、`npm run typecheck:web` |
| Web 构建 | `npm run build:web` |
| 静态检查 | `npm run lint`、`npm run format:check` |
| 手动集成／发布检查 | `npm run test:asr`、`npm run test:smoke`、`npm run test:smoke:asr`、`npm run test:package` |

按改动范围选择检查，不默认全部执行。安装、部署和备份步骤在[使用指南](../docs/setup.md)；模块依赖在[技术架构](../docs/architecture.md)。

## 运行边界

- 正式桌面包自带 Python；开发模式使用 `.venv` 或 `PAA_PYTHON`。macOS 与 Windows 分别验证，不推定所有系统版本和硬件均受支持。
- 公司 API／worker 使用同一业务包和数据库，桌面本地核心独立运行；Web 不依赖 `window.paa`。
- 公司聊天、图片理解和 ASR 调用外部 API；声纹提取使用独立 CPU 环境。部署资源限制由 Compose 管理。
- 原始材料、账号数据、密钥和用户模型缓存不入 Git；固定公共说话人权重随包分发，保留许可证。
- Web 与 Electron 独立维护 CSS，共享[视觉规范](../docs/design/README.md)和品牌图片。
- 桌面人工验收使用日常用户目录；自动故障测试使用临时数据，不能清理或破坏用户资料。
