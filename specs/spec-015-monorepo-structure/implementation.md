# Implementation — Spec 015

2026-09-15。按 [Plan](plan.md) 实施；未提交、推送或触发 CI，独立验收另见 acceptance。

## 迁移与清理

- 142 个原文件按 Plan 迁移；两个应用和三个共享包使用 npm workspaces。共享参数校验及 `JsonValue` 不再依赖桌面类型，桌面预设选择留在桌面；所有跨应用共享通过包导出访问。
- 根命令保持。应用专属 Vite／TS／Vitest／builder 配置归应用，共用 TS 基础、检查和发行协调工具归根。源码从各自应用构建；桌面共享代码编入 bundle，发行 `app.asar` 实测仅含 `out/`、`package.json`。
- Python 包名不变，桌面使用根 `.venv`，公司使用根 `.venv-server`／`.env.company`／私有资料；脚本从自身位置确定仓库根。更新开发子进程、解析器／探测资产、模型评测、PyInstaller、许可证、测试、Docker 与 CI 路径。
- 删除无运行、测试、动态入口或配置引用的 `CollapsibleSection.tsx` 及 5 组专属 CSS 规则；删除过时产品定义，由主 Agent 更新当前架构与历史引用。全仓 JS/CSS 导入和 Python AST 入口核对后，剩余无普通导入项均为 HTML／配置／命令入口、包导出、类型声明、包初始化或 Alembic 自动发现项，保留。
- 正式测试、夹具、手动 ASR 评测、指标 JSON、探测 WAV、许可证及全部迁移均保留。测试发现未减少：桌面 42、Web 27、core 92、server 109；桌面 E2E 仍为 4 文件／10 场景。
- 旧 `src/` 仅剩的 Python 缓存、旧 `tests/python/` 缓存和根 `out/` 8 个已被新输出替代的编译文件已清理，旧源码目录不再存在。保留用户资料、已下载模型、数据库卷、备份和验收证据。
- 539 个外部 package-lock 记录的 version／integrity 均与基线相同；仅改变 workspace 归属、链接和依赖分类，未升级外部依赖。

## 验证

实施按 S3：路径同时影响两端构建、Python 入口和分发资源。原始输出位于忽略的 `artifacts/spec015/`，下表是最终结果，不代表运行付费模型或真实录音。

| 检查 | 结果 |
| --- | --- |
| workspace 安装及 root postinstall | 离线 `npm install --ignore-scripts --offline`、锁文件校验与显式 desktop workspace 的 `npm run postinstall` 通过 |
| 桌面／Web 类型、Lint、格式 | `npm run typecheck`、`typecheck:web`、`lint`、`format:check` 通过；随后改动的两个 JS/TS 文件仅定向 Lint |
| 快速测试 | `test:unit` 42、`test:web` 27、`test:python` 92 通过；server 109 个用例均取得通过记录，分轮说明见下 |
| 普通构建 | `npm run build`、`build:web` 通过；共享包可实际编译，未重复运行通过的构建 |
| 桌面分发 | `build:core`、`electron-builder --dir`（已有普通构建后直接执行）、`test:package -- --runtime-only` 通过；无源 cwd／外部 Python／Node 的冻结核心 health、空记录、shutdown 与许可证均通过；asar 白名单核查通过 |
| 日常启动 | 主 Agent 的 `daily-startup.json`：根 `dev` 读取原 6 条会议、6 个模型和原设置，加密配置 hash 未变；`dev:company` 的 Web／API／worker 与原会话、看板正常，无新增业务或模型调用 |
| 公司 Docker | Compose 配置校验通过；使用相同精确版本的公共镜像前缀构建 service／web 成功；隔离网络的 service 容器导入 API／worker／parser、读取探测 WAV、发现 `0005_business_access` 及根路径校验通过；Web 容器静态产物存在 |

验证中修复的具体问题：

- 提取参数校验后，桌面 `summary-settings.ts` 原双函数导入遗漏了一处；改为分别从桌面和共享包导入，仅重跑失败的桌面类型／构建。
- 首次 server 使用旧的本地测试库密码，89 个 DB 用例在 fixture 连接前报认证错误；改为私下读取现有环境的连接信息且强制指向 `paa_company_test`，重跑失败项，20 个已通过的独立用例不重复。
- 上述复验 87 通过、2 个跨日测试失败：`test_company.py` 的日报日期和 `test_business_assistant.py` 的历史查询日期用 UTC `.date()` 筛选默认 `Company.rules.timezone = Asia/Shanghai` 的业务日。分别改用公司时区中的当前日期和已保存历史 revision 时间，定向 2 项通过；业务代码未改，未降低断言。
- Docker Web 首次镜像构建发现未复制公共 TS 基础配置，补 `COPY tsconfig.base.json` 后该 stage 通过；没有重跑本地成功构建。

官方 Docker Hub 的认证地址在本机解析到异常 IPv6 并超时，未完成原 registry 拉取。替代验证仅在忽略的临时 Dockerfile 给 Python 3.12.14、Node 24.20.0、Caddy 2.10.2 的相同 tag 加上 `docker.m.daocloud.io/library/` 前缀；项目 Dockerfile、daemon、DNS 和系统配置未切换镜像。上述成功证明迁移后的镜像构建／资产路径，不能宣称官方 registry 连通性已恢复。

`test:package` 新增显式 `--runtime-only`，只省略模型／公网推理诊断；默认完整验收保留，原 `--licenses-only` 保留。三种范围如实区分，runtime-only 输出使用独立后缀，不能覆盖旧完整推理证据。

## 独立验收后的依赖返工

根测试直接使用 React、ReactDOM 和公司 API 类型，已在根 devDependencies 补 `react = 19.2.8`、`react-dom = 19.2.8`、`@paa/api-contracts = 0.1.0`，不再依赖应用依赖被 hoist。离线同步锁文件后，仅根清单记录变化，539 个外部记录的版本与 integrity 不变；清单／锁文件核对和 Markdown 定向测试 4 项通过。证据为 `artifacts/spec015/dependency-rework-{audit,markdown}.json`，未重跑其他已通过项目；已由新的独立验收确认，见 [验收记录](acceptance.md)。

## 未验证范围

本次未执行 Windows 构建／安装卸载、完整桌面 E2E、ASR 模型矩阵、真实麦克风或付费 API。Windows 保持现有正常 PR／发布工作流；本机 macOS 结果不替代跨平台结论。目录迁移没有业务 schema／数据迁移。
