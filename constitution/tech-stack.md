# 技术栈与工程约束

## 当前状态

项目已完成 [Spec 001](../specs/spec-001-product-and-technical-foundation/spec.md)，具有 Electron 桌面入口、React 界面与 Python 本地核心，[独立工程验收](../specs/spec-001-product-and-technical-foundation/acceptance.md) 为 PASS。以下工程选择来自 [决策 0004](../.ai/decisions/0004-foundation-stack.md)，版本已核对 package-lock.json。真实录音、ASR 和 LLM 尚未接入。

## 技术基线

| 范围 | 选择 |
| --- | --- |
| 目标平台 | macOS / Windows；当前实机为 macOS ARM64 |
| 桌面 | Electron 44.3.0 |
| 界面 | React 19.2.8、TypeScript 5.9.3、CSS |
| 构建 | electron-vite 5.0.0、Vite 7.3.6、React 插件 5.2.0，满足兼容 peer 范围 |
| Node 工具链 | Node 24、npm 11、package-lock.json；通过 npm ci 复现 |
| Python | Python 3.12、venv + pip；当前仅标准库，无第三方运行依赖 |
| 通信 | Electron 主进程管理 Python 子进程，通过带请求 ID 的 JSON Lines / stdio 通信 |
| 本次核心 | 健康 / 能力状态、空会议列表及退出；不实现模型或录音 |
| 测试 | Vitest 4.1.11、Python unittest、Playwright 1.63.0 Electron smoke |
| 质量 | TypeScript、ESLint 9.39.5、Prettier 3.9.6、构建检查 |
| 分发 | 开发启动与构建预览；本次不制作签名安装包或内嵌 Python |

正式用户分发约束：应用自带所需运行时与内部处理程序，用户无需安装 Python / Node.js、创建 `.venv` 或手动启动核心。当前解释器选择逻辑仅为开发启动实现，正式安装包与资源路径适配尚未落地。详见 [决策 0005](../.ai/decisions/0005-self-contained-desktop-distribution.md)。

Node / Electron / Python 各自的运行边界、接口与退出行为见 [架构](../docs/architecture.md)。本机系统 Python 3.9 不作为项目基线；可用 Python 3.12 创建 `.venv`，不修改系统解释器。

## 目录约定

| 内容 | 位置 |
| --- | --- |
| 桌面主进程、preload、子进程客户端 | `src/desktop/` |
| React 界面 | `src/renderer/` |
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
| Python 环境 | 使用 Python 3.12 执行 `python -m venv .venv`，各平台命令见 README |
| 开发启动 | `npm run dev` |
| 构建与预览 | `npm run build`、`npm start` |
| 单元与协议测试 | `npm test` |
| Electron 冒烟测试 | `npm run test:smoke` |
| 类型检查 | `npm run typecheck` |
| 静态检查 | `npm run lint` |
| 格式检查 | `npm run format:check` |

## 配置与数据

- `PAA_PYTHON`：可选的 Python 可执行文件路径，不能包含任意 shell 命令。
- 默认优先项目 `.venv`，再使用平台适合的解释器命令；代码不写入开发机路径。
- 窗口在 Python 缺失时仍可打开并显示真实连接错误。
- 不要求 `.env`、LLM 密钥、模型文件或麦克风权限才能启动。
- 原始会议音频、转写、数据库和模型不进入版本库；当前不创建真实会议数据。
- 不运行本地业务 HTTP 服务或云服务，不输出整个环境变量或凭证。

## 后续能力方向

- SQLite + 原始数据文件为个人单机 MVP 的持久化起点，本次只定义契约，不创建业务数据库。
- sounddevice、faster-whisper / Whisper 是待设备验证的录音与 ASR 候选，不安装或下载模型。
- LLM 服务商、模型、密钥存储、文本外发规则在真实分析功能接入前确定。
- FastAPI、PostgreSQL、pgvector、LangGraph 当前不引入；是否需要由后续实际需求决定。
- 录音独立于 ASR / LLM，分块策略可配置；后台推理不进入 renderer 或录音回调。

## 验证边界

macOS ARM64 已通过类型、Lint、格式、构建、16 项 TypeScript 测试、7 项 Python 测试及 3 项真实 Electron 冒烟测试；开发启动与构建预览已实测。验证环境为 Node 24.20.0、npm 11.19.0、Python 3.12.14，详见 [实施报告](../specs/spec-001-product-and-technical-foundation/implementation.md)。

Windows 提供 CI 定义与路径逻辑检查，Windows 实机 / CI 尚未运行，不视为已验证。当前不承诺最低系统版本、安装包或模型实时性能。
