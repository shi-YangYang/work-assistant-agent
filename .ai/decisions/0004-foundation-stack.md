# Decision — Spec 001 工程实施基线

日期：2026-09-09

## Context

用户确定 Electron 桌面形态后明确要求“开始实施”。此前已展示的交付范围是产品确立、技术选型和最小可运行工程，不包含完整 Meeting Agent。协调 Agent 据此推进实施，并在既有授权内确定可逆的工程默认选择。

## Decision

| 范围 | 本次采用 |
| --- | --- |
| 桌面 | Electron 44，目标 macOS / Windows |
| 界面 | React 19 + TypeScript 5.9 + CSS，无额外组件库 |
| 桌面构建 | electron-vite 5 + Vite 7 + React 插件 5；按 peer dependency 兼容范围锁定 |
| Node 工具链 | Node.js 24，npm，提交 package-lock.json，使用 npm ci 复现 |
| Python 核心 | Python 3.12，标准库；venv + pip 工具链，当前无第三方运行依赖 |
| 桌面与核心通信 | Electron 主进程管理 Python 子进程，带请求 ID 的 UTF-8 JSON Lines / stdio；不监听 HTTP 端口 |
| 当前核心功能 | 健康 / 能力状态、空会议列表；不创建虚假会议，不接入录音或模型 |
| 后续持久化方向 | SQLite + 原始音频 / 转写文件；本次只设计数据契约，不创建会议业务数据库 |
| ASR / LLM | 保留 Provider 边界；本次不安装模型运行库、不下载模型、不选择付费服务商 |
| 质量检查 | TypeScript、ESLint、Prettier、Vitest、Python unittest、Playwright Electron smoke、构建 |
| 本次交付 | 开发环境可安装、可启动的桌面骨架与构建产物；不制作签名安装包或自动更新 |
| 平台验证 | 当前 macOS 实机验证；建立 Windows 验证配置并静态检查，Windows 实机 / CI 执行状态单独报告 |

桌面窗口应在 Python 不可用时仍然显示，并提供实际错误状态和重试方式。本次无会议录音，关闭最后窗口时退出应用并清理子进程，两平台一致；后续加入录音时再明确会议中的关闭行为。

Electron 与 React 等实际补丁版本以已生成锁文件为准。npm 元数据在本轮核对：Electron 44.3.0、electron-vite 5.0.0、React 19.2.8；electron-vite 5 当前 peer 范围只覆盖 Vite 5/6/7，因此不直接采用 registry 最新 Vite 8。

## Reason

- 在用户指定 Electron 和既有 Python 方向上建立真实的进程边界，后续录音与推理不进入 UI 线程。
- stdio 满足单机骨架的请求量，省去端口、服务发现和网络访问配置；未来音频以文件或专用队列传递，不把原始音频塞入控制消息。
- React / TypeScript 用于状态与契约表达；electron-vite 统一桌面、preload 与 renderer 构建。
- 当前 Python 只使用标准库，采用 venv 可减少初始化的额外工具要求；后续引入模型依赖时再评估是否切换依赖管理方案并留痕。
- SQLite 符合个人单机起步场景；无需为当前没有会议数据的骨架运行 PostgreSQL 或 pgvector。

## Alternatives

- HTTP / FastAPI：保留为后续扩展选项，本次没有跨客户端服务需求。
- 全 Node 核心：与用户既有 Python 方向及未来本地 ASR 接入不一致。
- 原生 JS 或重型组件框架：前者契约约束较弱，后者超出当前界面需求。
- 立即安装 faster-whisper、建立真实会议表或下载模型：超出骨架范围，硬件性能及数据保留细节应在功能接入时验证。

## Consequences

- `src/desktop/`、`src/renderer/`、`src/shared/`、`src/python/paa_core/` 分别承接桌面、界面、跨边界契约与 Python 核心。
- 用户无需提供密钥或麦克风权限即可查看应用；Python 缺失影响核心连接，不阻止窗口出现。
- 当前开发启动需要 Node 与 Python，不代表免环境安装包已经可用。
- Electron 44 的 npm 包按需下载二进制，而 electron-vite 5 直接读取 `path.txt`。项目显式配置 `postinstall: install-electron`，使正常 `npm ci` 完成二进制准备；首次安装需要下载 Electron，但不会下载 ASR 模型。该兼容性行为已核对实际安装包的 `package.json`、`index.js` 与 `install.js`，并需纳入干净安装验证。
- Windows 尚无当前会话可用运行环境，不以配置文件或 macOS 成功冒充 Windows 运行通过。

## Sources

查阅日期：2026-09-09。以上选择及取舍为结合官方能力与项目需求的工程判断。

- [Electron 进程模型](https://www.electronjs.org/docs/latest/tutorial/process-model)：main、renderer、preload 边界。
- [Electron 安全指导](https://www.electronjs.org/docs/latest/tutorial/security)：隔离、沙箱、有限 IPC 与导航权限。
- [electron-vite](https://electron-vite.org/guide/)：统一构建配置及开发入口。
- [React 与 TypeScript](https://react.dev/learn/typescript)：组件和类型配合。
- [Node child_process](https://nodejs.org/api/child_process.html)：异步子进程和 stdio。
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)：后续本地关系存储方向。
- [Python unittest](https://docs.python.org/3/library/unittest.html)：标准库测试工具。
