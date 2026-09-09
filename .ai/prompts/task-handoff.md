# Task Handoff — Spec 001 实施

## Current Status

Spec 001 已完成，见 [实施报告](../../specs/spec-001-product-and-technical-foundation/implementation.md) 与 [独立验收 PASS](../../specs/spec-001-product-and-technical-foundation/acceptance.md)。下文保留为本次实施交接记录，恢复任务时不要重复创建实施或验收 Agent，也不要重新初始化工程。后续会议能力由新的 Spec 推进。

## Role
Implementation。完成业务代码与工程配置，不能创建子 Agent，不负责最终验收。

## Goal
落实 Spec 001：产品与技术基础中的最小可运行 Electron 桌面工程，并返回可复现的验证结果。

## Context
用户已指定 Electron、macOS/Windows 目标，并明确“开始实施”。Spec 决策不创建子 Agent 验证的规则不取消业务实现后的独立验收。现有工作区含本轮未提交的规划文档，不能覆盖或重置。

## Project Mode
在已有目录骨架上增量实施，业务代码此前不存在。主 Agent 负责 constitution、Spec/Plan、产品定义、架构和决策，你负责代码与工程配置。

## Required Reading
AGENTS.md、constitution/mission.md、constitution/tech-stack.md、.ai/rules/spec-decision-workflow.md、当前 spec.md 与 plan.md、.ai/decisions/0004-foundation-stack.md、docs/product-definition.md、docs/architecture.md。

## Spec
specs/spec-001-product-and-technical-foundation/spec.md

## Scope
你拥有 src/、tests/、scripts/、根目录工程配置（package.json/package-lock、electron-vite、TS、ESLint、Prettier、Vitest、Playwright、pyproject、.nvmrc 等）、.github/workflows/、.gitignore、.env.example、README.md，以及当前 Spec 的 implementation.md。不要编辑主 Agent 正在维护的 constitution、spec.md、plan.md、docs/ 和 .ai/ 文档。

## Implementation Details
- Electron 44 + React 19 + TS 5.9 + electron-vite 5 + Vite 7 + React 插件 5。npm 锁依赖。最新 Vite 8 与 electron-vite 5 的 peer 范围不匹配，不要盲目采用。
- Node 本机24.20.0、npm11.19.0。Python3.12可执行文件临时用于创建本地 .venv：/Users/yang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3（3.12.14）。不要把这个路径写进代码或正式安装说明；不要替换系统 Python3.9。
- Python仅标准库，运行入口 src/python/paa_core，控制协议UTF-8 JSON Lines，请求id、成功result或error，至少健康/状态、会议列表（真实空列表）、退出。未知方法和无效结构返回错误。
- 无shell启动，解释器覆盖 PAA_PYTHON、项目.venv、平台fallback；Python版本不合适或缺失时，桌面必须正常出现并呈现错误/重试。
- Electron客户端有请求timeout、并发id关联、分块stdout处理、有限行/缓冲、错误/退出拒绝pending、重试不遗留旧进程、退出清理。核心进程日志走stderr，不输出敏感env。
- IPC只允许有限API，contextIsolation/sandbox开启、nodeIntegration关闭、拒绝设备权限、阻止任意导航/新窗口。不用全局禁用sandbox。开发服务只bind loopback。生产本地资源与CSP正确；不加载远程脚本。
- 界面中文，标题个人工作助手，浅色工作区、稳定侧栏、墨绿强调与细腻排版。会议主页诚实空状态，开始会议禁用且附近说明未接入；设置页展示核心真实状态和重试按钮。可标明周报/长期记忆后续支持，不伪造演示会议或模型就绪。不要在主界面堆叠Electron/Node/协议等开发信息。图标可使用兼容的lucide-react或SVG。
- 关闭最后窗口在两个平台都退出并清理Python；本次没有实际录音或后台常驻需求。
- 不安装ASR、不下载模型、不接付费API、不创建真实业务数据库。SQLite仅后续设计方向。
- 添加macOS/Windows的CI定义，当前不能宣称Windows已运行。无需签名、安装包或自动更新；npm build只是构建。

## Acceptance Criteria
除Spec AC外重点：真实Electron窗口可起；无key/model/mic仍可用；Python缺失下UI不白屏；正常连接实际Python；错误请求/异常输出/超时/退出路径有必要测试；正常与最小窗口尺寸UI可访问；无虚假功能。Python仅需unittest，不引入测试运行依赖。TS可Vitest；真Electron用Playwright（无需下载独立浏览器），输出截图到被忽略的artifacts目录。

## Commands
建立并运行：npm ci（锁文件生成后可验证）、npm run typecheck、npm run lint、npm run format:check、npm test、npm run build、npm run test:smoke。README提供 npm run dev 和 npm start。仅格式化自己负责的源码/配置，不批量格式化旧AGENTS或其他文档。

## Expected Output
完成后写 specs/spec-001-product-and-technical-foundation/implementation.md，含Summary、Files Changed、Important Decisions、Tests、Known Limitations、Remaining Questions。报告准确命令、结果、截图路径和Windows未验证等限制。不创建acceptance.md，不commit/push。中途有实质进展或阻塞及时消息主Agent。
