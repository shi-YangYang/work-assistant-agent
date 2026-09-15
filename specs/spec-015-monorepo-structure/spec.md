# Spec 015 — 多端仓库结构与无用文件清理

## 状态

DONE · 2026-09-15。已完成目录迁移与清理，并通过[独立验收](acceptance.md)；平台及镜像源验证限制见验收记录。理由见 [决策 0015](../../.ai/decisions/0015-multi-client-repository.md)，迁移映射及检查方案见 [Plan](plan.md)。

## 背景与当前行为

基线 `6e83d28` 有 278 个受 Git 管理的文件，根目录 28 个文件；当前 `src/` 同时容纳 Electron main、renderer、公司 Web、共享代码及两个 Python 包。一个根 package.json 管理两种客户端；桌面协议和公司 HTTP 类型混放，Python 核心与服务端虽有独立依赖，路径仍共用 `src/python`。

构建、Python 启动、测试、Docker 与 CI 存在硬编码路径。当前软件可以运行，问题是模块归属、依赖和文档不够清楚；不能以“整理目录”为由改变产品行为。初查已发现未使用的折叠组件、过时的产品定义及架构说明，具体处置见 Plan。

## 目标与目标结构

采用同仓库、独立应用与服务、显式共享包的结构。目录名属于本项目约定，不宣称存在唯一行业标准。以下为本轮实施目标：

```text
apps/
  desktop/                    # Electron 应用、专用配置与打包资源
    src/
      main/
      preload/
      renderer/
      shared/                 # 仅桌面内部使用的协议与数据
    core/                     # 随桌面分发的 Python 程序
      src/paa_core/
      pyproject.toml
      requirements.lock
      requirements-build.lock
  web/                        # 公司 Web、专用配置
    src/
services/
  company/                    # 同一后端的 API、worker、harness、迁移和资产
    src/paa_server/
    requirements.in
    requirements.lock
packages/
  api-contracts/              # 公司 HTTP 的 TypeScript 类型
  model-config/               # 现已被两端使用的纯参数校验
  ui-web/                     # Electron renderer／Web 共用 CSS
tests/
  desktop/
  core/
  server/
  web/
  e2e/desktop/
scripts/
  desktop/
  company/
  benchmarks/
  lib/
deploy/company/
docs/
AGENTS.md · constitution/ · specs/ · .ai/
```

根目录保留 npm workspace 配置、唯一 package-lock、共用工具配置、项目入口与环境示例；各应用配置归各应用。`tests/` 继续集中保存，按测试对象分区，避免本轮再建设一套测试体系。

## 功能需求

### R1 — 应用和依赖边界

- npm workspaces 管理实际存在的两个 JS 应用和三个共享包，各包显式声明自己的依赖和导出；沿用 Node、npm 及已锁定依赖版本，不引入新的构建调度框架。
- 应用可以依赖共享包，共享包不反向导入应用；不同应用不能通过相对路径直接读取彼此内部代码。不建立笼统的全仓 `common`／`utils` 收纳目录。
- Electron IPC／录音协议、桌面模型实测数据仍属于桌面；公司 HTTP 类型独立，后端权限、业务规则和模型密钥继续只在服务端。Python 程序沿用各自依赖与解释器环境，不伪装成 npm 包。
- `ui-web` 明确依赖浏览器 CSS 能力，不承诺原生移动界面直接复用。未来跨平台移动项目可放 `apps/mobile/`，独立原生项目可放 `apps/android/`、`apps/ios/`；实际立项时选择，本轮不创建空 App、SDK 或占位依赖。
- 移动端将通过公司 API 接入；不把 Electron 的本地核心、权限模型或会话实现强行变成跨端通用库。API 类型共享不代表已经实现移动客户端或自动生成多语言 SDK。

### R2 — 开发、打包和部署兼容

- 保留根目录现有 `npm run dev`、`dev:company`、`dev:web`、`dev:server`、`dev:worker`、`build`、`build:web` 及测试／打包／数据库命令入口，内部转发到正确位置。开发端口、Web 路由、HTTP／IPC 协议不变。
- 桌面仍以“个人工作助手”启动，appId、默认 userData、SQLite、录音、下载模型、加密配置及历史设置保持原位置；开发时不因 cwd 改变出现空资料库或要求重新下载。
- `.venv`、`.venv-server`、忽略的 `.env.company`／`.env`、私有材料目录和 Docker 卷不因源码迁移搬动。API 与 worker 仍使用同一后端包和数据库，不拆成微服务。
- 更新所有路径消费者：构建／类型／格式检查、测试发现、Python 子进程与 ASR spawn、模型评测、Docker COPY、CI 缓存键与产物路径。不能依赖个人绝对路径、旧目录残留或跨目录软链接才运行。
- 正式桌面包仍内置 Python 与依赖；包内容仅包含桌面所需文件，不夹带公司 Web 产物、后端、测试或用户资料。公司 Web 构建与服务镜像不依赖运行 Electron 或安装本地转写模型。

### R3 — 全项目清理

- 清理覆盖所有受 Git 管理的源码、测试／夹具、脚本、配置、资产与 Markdown；本机临时产物仅清理已确认过期且不含用户资料、备份或唯一证据的部分。
- 删除前核对导入、应用入口、测试自动发现、动态导入／子进程、构建和发布资源、CI／手动命令及文档引用。搜索不到普通 import 只构成候选，不能直接删除。
- 无入口的代码及仅服务它的样式可删除。测试只在功能已移除、断言被等效回归覆盖或确为过期临时脚本时删除，并记录替代关系；测试失败、运行较慢、不在日常 CI 中都不是删除理由。
- 过时产品说明归并到当前使命、路线图和 Spec；架构文档只维护当前系统关系，不复制逐轮实现和测试日志。历史需求、决策、失败／返工和验收依据通过原编号及固定 Git 快照追溯，不批量删除旧 Spec。
- 删除清单及理由归入本 Spec 实施报告，不新增永久清理台账；不要求必须凑够删除数量。保留仍使用的迁移、基准数据、测试夹具、许可证、锁文件和关键验收证据。

## 非目标、技术约束与边界

本轮不开发 Android／iOS，不更换 React、Electron、Python、数据库或 harness，不重写业务大模块，不调整权限／数据 schema，不接入新云服务。只提取已经共同使用的代码，不预建统一客户端 SDK、原生设计系统或通用 Agent 平台。

保留 `AGENTS.md`、`constitution/`、`specs/`、`.ai/` 的位置和职责；本 Spec 确认后，仅对列明的业务目录与工程文件执行结构迁移。历史文档引用用 Git 固定版本或新入口说明处理，不能改写当时的验收事实。

CI 仅适配现有工作流路径与命令，不增加触发次数或默认重型任务。实施涉及构建、跨模块路径和发布资源，按 S3 验证受影响范围；文档维护按 S0。

## 验收标准

- [x] 所有业务源码按目标职责归属，根目录不再承担多个应用的专用配置；无旧源码副本、占位 App 或未声明的跨应用导入。
- [x] workspace 安装及各端构建可独立寻址，共享包运行时导入可解析，已有根命令继续可用。
- [x] Electron 日常启动可读取原会议、模型与设置；Web／API／worker、数据库迁移及附件／探测资产路径有效。
- [x] 当前平台桌面打包与核心资源定向校验、公司 Docker 相关构建检查完成；其他平台结果如实记录，不冒称跨平台已验。
- [x] 删除项都有引用／入口检查或替代依据；测试发现的减少有解释，权限、持久化、恢复等有效回归未丢失。
- [x] 当前文档、工具配置及 CI 无失效路径；历史证据仍可追溯，不把老版本状态当现状。
- [x] 相关自动检查和一次必要的日常启动验证通过，已通过项不无理由重复；独立验收完成，用户资料及密钥未被清理或迁移。

## 待确认问题

无。本方案已由用户确认并启动；未来移动技术选型留到移动端 Spec。
