# Personal Agent Assistant

面向 macOS 和 Windows 的个人工作助手，从会议记录起步，逐步连接周报与历史工作信息，帮助个人回顾讨论、跟踪行动与积累长期记忆。

当前已建立 **Electron + React + TypeScript 桌面骨架与 Python 本地核心**：可启动中文会议工作区、查看真实核心状态和空会议列表，并在核心不可用时重试。录音、本地 ASR、LLM 纪要、周报和长期 Memory 尚未接入；“开始会议”处于禁用状态，不会采集音频或生成虚假记录。

## 背景

首个业务目标是 Meeting Agent MVP：持续录音 → 本地转写并保存完整记录 → 结束会议 → 整理结构化纪要。采集必须独立于 ASR / LLM，不能因推理延迟中断。目标与边界见 [产品定义](docs/product-definition.md)、[项目使命](constitution/mission.md) 和 [路线图](constitution/roadmap.md)。

本次交付为 [Spec 001](specs/spec-001-product-and-technical-foundation/spec.md) 的产品与工程基础，不代表完整 Meeting Agent 已交付。

## 开发环境安装

以下步骤面向开发者。正式用户版本的交付要求是安装应用后直接使用，由应用自带所需运行时，不要求用户安装 Python、Node.js 或手动启动后台进程。**当前仓库尚未实现这种安装包**，下列源码启动方式仍需要准备开发环境。

准备 Node.js **24**、npm **11** 和 Python **3.12**。项目不依赖 Python 第三方包；无需模型、LLM 密钥或麦克风权限。首次 Node 依赖安装会通过 `postinstall` 下载 Electron 二进制，需要网络，下载内容不包含 ASR 模型。

macOS：

```sh
python3.12 -m venv .venv
npm ci
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
npm ci
```

如果 Python 3.12 的命令名称不同，请用对应解释器执行 `-m venv .venv`，不要替换系统 Python。启动时自动使用项目 `.venv`，无需激活虚拟环境。

如果 Electron 下载因网络不可达而失败，可参考 [Electron 安装文档](https://www.electronjs.org/docs/latest/tutorial/installation) 配置网络或镜像，然后重新执行 `npm ci`。Electron 44 的二进制安装通过项目 `postinstall: install-electron` 显式完成，避免第一次启动时才发现缺少桌面运行时。

## 使用

开发启动：

```sh
npm run dev
```

构建后启动：

```sh
npm run build
npm start
```

应用默认打开“会议记录”，在“设置”中查看核心连接与尚未接入的会议能力。开发 UI 服务仅绑定 `127.0.0.1:5173`；Python 控制核心通过标准输入输出通信，不监听网络端口。构建预览加载本地资源。关闭最后窗口时退出应用，并停止其管理的 Python 进程；macOS 与 Windows 采用相同行为。

`npm run build` 仅生成 `out/` 编译产物，不生成安装包。当前需要从本仓库运行，尚未内嵌 Python、签名、公证或实现自动更新。

### Python 配置与连接问题

解释器选择顺序：`PAA_PYTHON` 可执行文件路径 → 项目 `.venv` → macOS 的 `python3` 或 Windows 的 `py -3.12`。若找到的解释器不是 Python 3.12，应用显示版本提示；未找到解释器时仍显示完整窗口，不白屏。

可在启动前指定解释器（示例路径需替换）：

```sh
PAA_PYTHON="/absolute/path/to/python3.12" npm run dev
```

```powershell
$env:PAA_PYTHON = 'C:\path to Python312\python.exe'
npm run dev
```

`.env.example` 只说明配置，**应用不自动加载 `.env` 文件**。`PAA_PYTHON` 只能是可执行文件路径，不能附加命令或参数；路径含空格可用。修复项目 `.venv` 后可点击“重新连接”。更改终端环境变量后需重新启动应用使新变量生效。

## 开发与验证

| 命令 | 检查内容 |
| --- | --- |
| `npm run typecheck` | 桌面、跨边界契约、界面和测试的 TypeScript 类型 |
| `npm run lint` | ESLint 与 React Hooks 检查 |
| `npm run format:check` | 源码和工程配置的 Prettier 格式 |
| `npm run format` | 格式化上述文件，不批量重排开发规范文档 |
| `npm test` | Vitest 进程边界测试与 Python unittest |
| `npm run build` | main / preload / renderer 构建 |
| `npm run test:smoke` | 构建并启动真实 Electron，验证正常/异常核心连接、UI 与退出清理 |

Smoke 使用 Electron 自带 Chromium，无需 `playwright install` 下载浏览器；它会打开短暂的桌面窗口，需要可用图形会话。截图位于被 Git 忽略的 `artifacts/`。测试不需要录音、模型或外部 LLM。

当前实际运行环境为 macOS ARM64；Windows 已提供 [CI 定义](.github/workflows/ci.yml) 与平台路径处理，**Windows 实机/CI 尚未运行验证**。本机检查与限制见 [实施报告](specs/spec-001-product-and-technical-foundation/implementation.md) 和 [独立验收报告](specs/spec-001-product-and-technical-foundation/acceptance.md)，本次骨架验收为 PASS。

开发遵循 [AGENTS.md](AGENTS.md)：Spec 讨论、决策与文档由协调 Agent 自行检查，不派子 Agent 验证决策；工程代码实施后仍进行独立验收。开发中的 Agent 分工与产品是否实现多 Agent 是不同问题。

## 目录

```text
src/
├── desktop/              # Electron 主进程、preload、Python 客户端
├── renderer/             # React 中文桌面工作区
├── shared/               # 有限 IPC API 与状态类型
└── python/paa_core/       # Python 标准库 JSON Lines 核心
tests/
├── desktop/              # 进程客户端与生命周期测试
├── python/               # 协议与真实能力测试
└── smoke/                # 真 Electron 启动与故障检查
scripts/                  # 工程辅助脚本
docs/                     # 产品定义与架构
constitution/             # 项目使命、路线图与技术约束
specs/                    # Spec、实施与验收报告
.ai/                      # 决策、规则与任务交接
AGENTS.md                 # 开发规范
```

Electron renderer 启用沙箱与上下文隔离，关闭 Node integration，preload 只公开状态、重试和会议列表 API。当前拒绝设备权限，阻止外部页面导航和新窗口，不加载远程脚本。设计与后续 ASR / LLM / SQLite 边界见 [架构](docs/architecture.md)、[工程基线](.ai/decisions/0004-foundation-stack.md) 和 [技术约束](constitution/tech-stack.md)。

本地音频、转写、数据库、模型与密钥不得进入版本库；当前没有业务数据库或真实会议数据。

## 许可证

[MIT](LICENSE)。
