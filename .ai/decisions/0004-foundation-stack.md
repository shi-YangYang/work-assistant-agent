# 桌面工程基线

当前精确版本与命令以 [技术栈](../../constitution/tech-stack.md) 和锁文件为准。

## 决定

| 范围 | 选择 |
| --- | --- |
| 桌面与界面 | Electron 44、React 19、TypeScript 5.9、CSS |
| 工具链 | Node 24、npm / package-lock；electron-vite 5、Vite 7 |
| 本地核心 | Python 3.12，venv / pip；骨架阶段仅标准库 |
| 通信 | main 管理无 shell 的 Python 子进程，带请求 ID 的 UTF-8 JSON Lines / stdio |
| 存储方向 | SQLite + 原始数据文件，按后续功能增量接入 |
| 质量工具 | Vitest、unittest、Playwright Electron、TypeScript、ESLint、Prettier |

初始目录分别为 `src/desktop/`、`src/renderer/`、`src/shared/`、`src/python/paa_core/`；用户已在 [多端仓库与共享边界](0015-multi-client-repository.md) 批准迁入桌面 workspace，当前路径以技术栈为准。renderer 经有限 preload API 调用核心；Python 缺失时窗口仍可打开并重试。音频不进入控制消息，录音和推理与 UI 解耦。

## 取舍与约束

- stdio 满足桌面单机控制需求，桌面核心不引入 HTTP / FastAPI、PostgreSQL、pgvector 或编排框架；公司服务另有独立边界，ASR / LLM 保留 Provider 接口。
- React / TypeScript 用于状态与契约；不引入额外组件库。electron-vite 5 的 peer 范围包含 Vite 7，不能无依据升级到不兼容大版本。
- Electron 44 的按需下载与 electron-vite 读取 `path.txt` 的行为不同，因此由 postinstall 显式调用 `install-electron`，保证 `npm ci` 准备运行时；首次安装需要网络。
- CI 分为日常检查与按风险触发的重检查，避免每次提交都运行真实模型和安装卸载。开发使用长期 `dev`，通过 CI 和 PR 后合入 `main` 并回同步；具体测试矩阵见 [CI 工作流](../../.github/workflows/ci.yml)，分支操作见 [分支规则](../rules/git-branch-workflow.md)。

## 依据

[Electron 进程模型](https://www.electronjs.org/docs/latest/tutorial/process-model)、[安全指导](https://www.electronjs.org/docs/latest/tutorial/security)、[electron-vite](https://electron-vite.org/guide/)、[Node 子进程](https://nodejs.org/api/child_process.html)。运行结果见 [骨架验收](../../specs/spec-001-product-and-technical-foundation/acceptance.md)。
