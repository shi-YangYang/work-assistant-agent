# Plan — 多端仓库结构与无用文件清理

本文件是 [Spec 015](spec.md) 的已确认迁移方案，2026-09-15 开始实施。基线为 `6e83d289a16a0783705ae17c879d39d1e059e839`；实施开始重新确认工作区及新增文件，保留用户改动。

## 路径映射

| 当前位置 | 目标 | 说明 |
| --- | --- | --- |
| `src/desktop/` | `apps/desktop/src/main/` | `preload.ts` 单独移至 `src/preload/index.ts`；无关内部重命名不扩展 |
| `src/renderer/` | `apps/desktop/src/renderer/` | 迁移使用中的组件，删除确认无引用的旧组件 |
| `src/shared/` 的桌面契约、实测 JSON | `apps/desktop/src/shared/` | 不作为所有终端的协议 |
| `src/shared/company-contracts.ts` | `packages/api-contracts/src/index.ts` | 维持现有 HTTP DTO 语义，不新增 API |
| `src/shared/reasoning.ts` | 公共校验至 `packages/model-config/src/`；预设选择留桌面 | `validateParameters` 及纯 JSON 类型共享；`selectedParameters`／桌面 `ModelPresets` 不使 Web 依赖桌面契约 |
| `src/ui/` | `packages/ui-web/src/` | 通过包导出 CSS，保持主题变量及类名 |
| `src/web/` | `apps/web/src/` | 包含 HTML 入口；Web 专用组件留本应用 |
| `src/python/paa_core/`、`pyproject.toml`、`requirements.lock`、`requirements-build.lock` | `apps/desktop/core/` 对应源码／元数据／锁文件 | Python import 包名 `paa_core` 不变 |
| `src/python/paa_server/`、`requirements-server.in`／`.lock` | `services/company/src/paa_server/`、`requirements.in`／`.lock` | 包名、Alembic revision 和资源文件保留；API／worker 共用 |
| Electron、Web Vite 配置与专用 TS／Vitest 配置 | 各自 `apps/desktop/`、`apps/web/` | 根保留共用 TS 基础、ESLint／Prettier、跨端 Playwright 入口 |
| `scripts/company.mjs` | `scripts/company/run.mjs` | 从脚本文件位置确定仓库根，继续提供原根命令 |
| 桌面安装／测试／打包脚本、`core-licenses.py` | `scripts/desktop/` | 许可证兜底文件归 `apps/desktop/resources/licenses/` |
| `scripts/python-command.mjs` | `scripts/lib/python-command.mjs` | 工程脚本共用；有调用方的桌面 TS 适配器不因相似而删除 |
| `scripts/spec013-benchmark.py` | `scripts/benchmarks/local-asr.py` | 保留可复现实测入口及原始来源，更新 Spec 013 链接 |
| `tests/python/`、`tests/smoke/` | `tests/core/`、`tests/e2e/desktop/` | 其余测试分区保留；同步自动发现、fixture、mock 和子进程路径 |
| `out/main`／`preload`／`renderer` | `apps/desktop/out/` 下同名子目录 | 桌面 package main 为 `out/main/index.js`，builder app 目录为该 workspace |
| `out/web/` | `apps/web/out/` | Caddy 构建阶段只复制该产物 |

发行产物继续使用根 `dist/desktop/`、`dist/core/`，PyInstaller 中间产物仍在 `build/core/`。`deploy/company/`、根环境文件与虚拟环境保持原位置。迁移完成后删除空的旧 `src/`；根 `tests/` 和固定治理目录保留。

## 初查清理清单

| 对象 | 处置与依据 |
| --- | --- |
| `src/renderer/CollapsibleSection.tsx` | 删除候选；全仓运行代码、测试和配置无导入／调用，仅旧 Spec 006 Plan 提及。实施前复核动态入口；同时删除只属于该组件的样式，不能误删现用 `<details>` 组件 |
| `docs/product-definition.md` | 删除；“纪要尚未实现、产品不是团队 SaaS、绿色强调”等描述已过时。有效产品原则归使命／当前 Spec，旧文本由基线 Git 保留；更新 `docs/README.md`、README 及其他引用 |
| `docs/architecture.md` | 保留并重写为当前桌面＋Web／公司服务的简明架构入口；详细协议引用对应 Spec，旧 schema／延期技术及历史 CI 声明不再当现状 |
| 其余 Markdown／源码／测试 | 逐项检查；重复内容归唯一归属，证据不足先保留，不宣称初查已证明全仓没有死代码 |
| `0005_business_access.py` 等迁移 | 保留；Alembic 自动发现，普通 import 搜索不能识别用途 |
| `real_asr_check.py`、`smoke_core.py`、`summary_fixture.py`、`document_samples.py`、`document_fakes.py` | 保留并迁移引用；现有手动命令／smoke／server 测试仍调用 |
| 本地模型评测脚本、指标 JSON、`probe-zh.wav`、许可证 | 保留；分别支撑指标复现、UI、模型服务连通性与分发，不是临时废文件 |

初查针对 278 个已跟踪文件做了文件／引用清点，没有发现字节完全相同的非空文件；这不替代实现阶段的入口检查。删除项及替代引用写入最终 implementation.md，具体 Git diff 是变更清单。

## 实施顺序与关键约束

1. **确认边界与基线**：记录文件归属、当前测试发现与调用入口，核对本轮之后新增文件。先迁移后清理，避免将移动误记为删除；用 Git rename 保留历史。迁移与业务行为修改分开审查。
2. **建立 workspace**：根保留私有仓库清单、唯一 package-lock 和用户熟悉的命令；运行依赖各自声明，共用开发工具可留根。只生成必要的 workspace 锁文件变化，不删除重建锁文件或顺便升级依赖；不得依赖安装器碰巧 hoist 的未声明依赖。
3. **移动应用与共享代码**：按映射改导入和 exports。内部 TS 包由应用构建编译／打包，Electron 发行运行时不得直接引用源码 `.ts`、仓库软链接或仅由 TS paths 识别的别名；纯包不能导入 Electron／DOM 能力。不在客户端共享服务端授权实现。
4. **迁移 Python 和资源**：所有 `PYTHONPATH`、脚本 `sys.path`、PyInstaller `--paths`／入口、spawn、Alembic、探测 WAV 和 parser 子进程使用新路径。开发桌面 app.getAppPath 改变后，分别定位桌面 core 与根 `.venv`；正式包仍只启动 `process.resourcesPath/paa-core`。保留 app.setName、appId、应用版本及默认 userData。
5. **修订工程入口**：npm root 命令转发，脚本从自身位置定位仓库根，避免 workspace cwd 变化读错 `.env.company`、测试库／私有目录或锁文件。桌面 builder 采用明确文件白名单；安装测试同步 appPath 内输出路径，许可证清单指向迁移后的原锁文件。
6. **修订 Docker／CI**：Docker 安装前提供所需 workspace manifests 和根锁文件，Web 阶段按 workspace 安装／构建，后端仅复制公司包及依赖。保持 Compose project 名、卷名、挂载、环境及服务命令。CI 只更新路径、缓存、命令和上传产物；保留既有 PR／tag／手动触发与任务分层。
7. **清理与文档收尾**：先确认候选不被入口、自动发现、运行时字符串、资源打包或手动工具使用，再删除。更新根 README、docs 入口、技术栈与相关历史链接；旧 Plan 的当时方案用固定版本链接或简短历史注释处理，不篡改既有验收。更新递归 ignore／格式／Lint glob，覆盖新源路径并排除构建产物。

## 验证、风险与回滚

决策阶段只做 S0 文档自查。实施为 S3，理由是同时改变两端构建、Python 入口、Docker COPY 与发行包资源定位；检查限于这些具体影响，不调用付费模型或重新跑 ASR 模型矩阵。

- **入口与发现**：检查根命令转发、包依赖与运行时导入、测试发现数量和删除依据；旧路径只允许出现在本迁移记录或明确的历史引用中。避免测试 glob 漏扫而“零测试通过”。
- **相关自动检查**：在最终相应代码上执行现有桌面／Web 类型、Lint、格式、快速测试、两套 Python 子系统测试和普通构建，各项一次；必要失败只重跑受修复影响的项目。共享包检查纳入实际消费入口，不能因为搬出 `src/shared` 漏检。
- **桌面入口与发行资源**：在用户项目目录 `npm run dev` 打开日常环境，确认原会议、模型和设置仍可见；不需新录音或真实模型请求。本机对迁移影响的 PyInstaller 核心及 `package:dir`／`test:package` 做一次组合检查，校验资源与许可证，不叠加安装卸载全流程。
- **公司服务与容器**：新路径下启动 Web／API／worker，验证健康、现有页面及迁移资产定位；迁移发现检查用专用测试库，不为目录变更修改日常 schema。核对 Compose 后构建受影响的 service／web stages，验证 Python import／探测资产与静态产物存在，不部署生产环境。
- **平台限制**：macOS 本地通过不等于 Windows 通过。现有 Windows 快速检查随正常 PR 执行；完整 Windows 分发仍按既有发布／手动规则，未执行如实记录，不擅自启动额外 CI 或用反复重试代替修复。
- **回滚**：本轮无数据迁移，源码可通过反向提交恢复至基线结构，再按锁文件安装；用户资料和 Compose 卷保持原位置。不得通过 reset、删除卷或覆盖用户修改来恢复。目录迁移若暴露行为缺陷，应单独说明具体问题，不把无关产品改造混入本轮。

实施由一个 Agent 串行完成耦合路径迁移，再由新的独立 Agent 验收；报告只保留结果、删除理由和未验证范围。提交／推送仍等待用户另行指令。
