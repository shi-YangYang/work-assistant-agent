# Plan — 产品与技术基础

## 状态

`DONE` — 代码实施与独立工程验收已完成，验收为 PASS，无需返工。结果见 [实施报告](implementation.md) 与 [验收报告](acceptance.md)；产品、技术及实施边界见 [Spec](spec.md)、[产品定义](../../docs/product-definition.md)、[架构](../../docs/architecture.md) 和 [决策 0004](../../.ai/decisions/0004-foundation-stack.md)。

Spec 决策及文档自查由协调 Agent 完成，不创建子 Agent 验证决策。业务实现交给一个实施 Agent，结束后创建新的独立验收 Agent。

## 涉及模块

| 模块 | 职责与边界 |
| --- | --- |
| `src/desktop/` | Electron 主进程、preload、Python 客户端、受限 IPC 与生命周期 |
| `src/renderer/` | React/TS 中文会议工作区、空状态、设置与真实能力状态 |
| `src/shared/` | 桌面 / 界面共享的类型契约 |
| `src/python/paa_core/` | 标准库 stdio 核心，健康 / 能力、空会议查询及退出 |
| `tests/` | Vitest、Python unittest、Electron smoke |
| `scripts/` | 开发验证辅助工具，可在已固定基础目录外扩展 |

## 修改顺序

1. 协调 Agent 完成产品、架构与决策记录，细化 Spec 并创建实施交接。
2. 实施 Agent 建立 package.json、package-lock、electron-vite、TS 和质量工具配置，保留已存在目录和用户修改。
3. 建立 Python 核心及无 shell 子进程客户端，处理缺失、超时、进程退出和重试，桌面启动不依赖核心成功。
4. 建立隔离的 Electron 窗口和限定 preload API，再接入 React UI；默认不请求设备权限、不调用外部模型。
5. 增加实际需要的测试、CI 和构建配置，更新 README 的真实安装与运行命令。
6. 实施 Agent 执行验证、处理失败并写 `implementation.md`。
7. 新的验收 Agent 独立检查实现、测试与 Spec，写 `acceptance.md`；如失败交新实施 Agent 返工。
8. 协调 Agent 同步最终状态、验证限制及剩余事项，交付应用骨架。

## 数据流

```text
React UI → preload 限定 API → Electron 主进程
                                  ↓ stdio JSON Lines
                              Python 核心
                                  ↓
                           状态 / 能力 / 空会议列表
```

当前不实现音频或模型链路；其设计位于 `docs/architecture.md`。

## 接口变化

Python 采用 UTF-8 JSON Lines，带 ID 的成功 / 错误响应；实现健康 / 状态、会议列表和退出，具体方法常量与类型由实施 Agent 集中定义。未知方法和非法数据返回错误，主进程对超时、无效输出及退出做有界处理。

preload 只公开实际 UI 使用的方法，不能向 renderer 暴露任意进程、文件或 IPC 操作。`PAA_PYTHON` 可覆盖解释器路径；项目 `.venv` 为推荐本地环境，代码不含本机绝对路径。

## 测试计划与命令

以下工程命令已建立并完成本机验证，具体证据及未执行的平台项见实施 / 验收报告。

| 命令 | 目的 |
| --- | --- |
| `npm ci` | 根据锁文件安装 Node 依赖 |
| `npm run dev` | 开发启动 Electron 窗口 |
| `npm run build` | 编译 main / preload / renderer |
| `npm start` | 启动构建后的应用 |
| `npm run typecheck` | TypeScript 检查 |
| `npm run lint` | 静态检查 |
| `npm run format:check` | 工程源码格式检查，避免批量重排既有开发规范 |
| `npm test` | TypeScript 核心测试与 Python 标准库测试 |
| `npm run test:smoke` | 真 Electron 启动与关键状态检查 |

关键验证：无模型 / 密钥 / 麦克风权限可启动；Python 缺失时 UI 降级；跨边界请求正确关联；非法消息和超时不挂住；关闭应用停止子进程；无虚假会议与真实模型请求；界面在默认与最小尺寸可用。

平台范围：macOS 本机运行及截图核对；配置 Windows CI 并静态检查，未运行的 Windows 项必须写明。构建产物不等于安装包，未验证平台不写通过。

## 风险

- Electron 与构建插件版本必须满足 peer dependency；使用已核对的 Vite 7 兼容线，不盲目安装最新 Vite 8。
- 当前 macOS 系统 Python 为 3.9，不满足项目基线；使用 Python 3.12 创建本地 `.venv`，不替换系统解释器。
- 当前骨架包含真实进程边界，需特别验证退出清理和异常请求，避免仅通过 UI 空页面判断完成。
- Windows 无当前运行环境，不能以静态检查替代端到端结论。

## 迁移策略

没有业务数据或旧 API 迁移。保留 `src/`、`tests/`、`docs/` 与固定 Agent 结构，只按需移除占位文件。沿用现有 LICENSE、Git 历史及用户未提交文档。

## 预计涉及文件

业务与工程：`src/desktop/`、`src/renderer/`、`src/shared/`、`src/python/paa_core/`、`tests/`、`scripts/`、根目录 Node/Python 配置和锁文件、`.github/workflows/`、`.gitignore`、`.env.example`。

文档：`README.md`、`docs/product-definition.md`、`docs/architecture.md`、`docs/README.md`、`constitution/`、当前 Spec/Plan、`.ai/decisions/0004-foundation-stack.md`、实施任务交接、实施和验收报告。
