# 决策 0004 — 桌面工程基线

2026-09-09 · 已落地；当前精确版本与命令以 [技术栈](../../constitution/tech-stack.md) 和锁文件为准。

## 决定

| 范围 | 选择 |
| --- | --- |
| 桌面与界面 | Electron 44、React 19、TypeScript 5.9、CSS |
| 工具链 | Node 24、npm / package-lock；electron-vite 5、Vite 7 |
| 本地核心 | Python 3.12，venv / pip；骨架阶段仅标准库 |
| 通信 | main 管理无 shell 的 Python 子进程，带请求 ID 的 UTF-8 JSON Lines / stdio |
| 存储方向 | SQLite + 原始数据文件，按后续功能增量接入 |
| 质量工具 | Vitest、unittest、Playwright Electron、TypeScript、ESLint、Prettier |

`src/desktop/`、`src/renderer/`、`src/shared/`、`src/python/paa_core/` 分别承接桌面、界面、契约与核心。renderer 经有限 preload API 调用核心；Python 缺失时窗口仍可打开并重试。音频不进入控制消息，录音和推理与 UI 解耦。

## 取舍与约束

- stdio 满足单机控制需求，暂不引入 HTTP / FastAPI、PostgreSQL、pgvector 或编排框架。ASR / LLM 保留 Provider 边界，选型在相应 Spec 落地。
- React / TypeScript 用于状态与契约；不引入额外组件库。electron-vite 5 的 peer 范围包含 Vite 7，不能无依据升级到不兼容大版本。
- Electron 44 的按需下载与 electron-vite 读取 `path.txt` 的行为不同，因此显式使用 `postinstall: install-electron`，保证 `npm ci` 准备运行时；首次安装需要网络。
- Spec 001 只交付开发骨架，不含录音、模型、业务数据库或安装包。正式用户无需安装运行时的约束见 [决策 0005](0005-self-contained-desktop-distribution.md)。
- 2026-09-11 用户确认将 CI 分为日常检查与按风险触发的重检查，避免每次提交都运行真实模型和安装卸载。开发使用长期 `dev`，通过 CI 和 PR 后合入 `main` 并回同步；具体测试矩阵见 [README](../../README.md#ci-分层)，分支操作见 [分支规则](../rules/git-branch-workflow.md)。

## 依据

2026-09-09 查阅并结合实际安装包核对：[Electron 进程模型](https://www.electronjs.org/docs/latest/tutorial/process-model)、[安全指导](https://www.electronjs.org/docs/latest/tutorial/security)、[electron-vite](https://electron-vite.org/guide/)、[Node 子进程](https://nodejs.org/api/child_process.html)。运行结果见 [Spec 001 验收](../../specs/spec-001-product-and-technical-foundation/acceptance.md)。
