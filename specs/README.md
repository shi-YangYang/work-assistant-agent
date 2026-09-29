# Specs

[Spec 001～025 摘要](history-001-025.md)

| Spec                                                    | 内容                                               | 状态与验证                                                                               |
| ------------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| [026](spec-026-web-design-refresh/spec.md)              | Web 黑白灰设计、助手交互与响应式                   | 已实施；[验收 PASS](spec-026-web-design-refresh/acceptance.md)                           |
| [027](spec-027-desktop-design-refresh/spec.md)          | Electron 黑白灰设计、全屏画布与会议交互            | 已实施；[macOS 验收 PASS，Windows 未实测](spec-027-desktop-design-refresh/acceptance.md) |
| [028](spec-028-company-backend-architecture/spec.md)    | 公司后端迁入 apps/server，拆分业务模块与 harness   | [验收 PASS](spec-028-company-backend-architecture/acceptance.md)                         |
| [029](spec-029-task-retry-progress/spec.md)             | 工作助手 Agent 节点重试与执行进度展示              | [验收 PASS](spec-029-task-retry-progress/acceptance.md)                                  |
| [030](spec-030-project-quality-repair/spec.md)          | 功能代码、UI 设计、流程设计、目录结构四维修复      | [验收 PASS](spec-030-project-quality-repair/acceptance.md)                               |
| [031](spec-031-assistant-persona/spec.md)               | 工作助手可切换“大包／专业”人设                     | [验收 PASS](spec-031-assistant-persona/acceptance.md)                                    |
| [032](spec-032-work-assistant-task-delivery/spec.md)    | 工作助手任务协助、连续修改、轻量联网与自主汇报     | [验收 PASS](spec-032-work-assistant-task-delivery/acceptance.md)                         |
| [033](spec-033-assistant-context-usage/spec.md)         | 会话 JSONB 上下文、模型窗口用量与 90% 自动压缩     | [验收 PASS](spec-033-assistant-context-usage/acceptance.md)                              |
| [034](spec-034-assistant-interrupt-progress/spec.md)    | 工作助手单会话发送限制、中断与任务执行光带         | [验收 PASS](spec-034-assistant-interrupt-progress/acceptance.md)                         |
| [035](spec-035-assistant-task-consistency/spec.md)      | 工作助手多轮任务、授权承接、恢复与完成判断统一     | 已完成，验收通过                                                                         |
| [036](spec-036-assistant-permissions-questions/spec.md) | 工作助手三级执行权限与临时回答框                   | [验收 PASS](spec-036-assistant-permissions-questions/acceptance.md)                      |
| [037](spec-037-assistant-work-reference/spec.md)        | 从工作或输入框引用工作，复用最近聊天并读取最新内容 | 已完成                                                                                   |
| [038](spec-038-assistant-response-delivery/spec.md)     | 开放式任务直接交付、结构化收尾与按需核对           | 已完成，验收通过                                                                         |
| [039](spec-039-assistant-request-efficiency/spec.md)   | 工作助手读请求共享、刷新去重与身份隔离             | 已完成；[验收通过](spec-039-assistant-request-efficiency/acceptance.md) |
| [040](spec-040-company-cloud-assistant-brand/spec.md) | Noria 产品定义与 Web／Electron 全端品牌更新        | [验收 PASS，含实测范围与限制](spec-040-company-cloud-assistant-brand/acceptance.md) |
| [041](spec-041-web-session-lifetime/spec.md) | Web 登录闲置续期与 30 天最长有效期 | [验收 PASS](spec-041-web-session-lifetime/acceptance.md) |
| [042](spec-042-general-assistant-sandbox/spec.md) | 通用问答、隔离代码执行与文件成果交付 | 已完成 |
| [043](spec-043-project-directory-organization/spec.md) | Web、公司后端与 Electron 代码按职责归组 | [验收 PASS](spec-043-project-directory-organization/acceptance.md) |
| [044](spec-044-web-full-system-testing/spec.md) | Web 全功能、真实 Agent 多轮与破坏性测试 | 部分修复，2 类技术问答未通过 |

## 文档分工

- 历史摘要：每个 Spec 简述做了什么，原始细节可从 Git 查阅。
- `spec.md`：需求、边界、验收标准。
- `plan.md`：实施步骤和必要验证。
- `acceptance.md`：实际验收结果、证据与未解决问题。

## 生命周期

新 Spec 从 **045** 继续，使用 `spec-XXX-short-name/` 和 [_template](_template/)。主 Agent 确认需求后，由实施 Agent 开发、独立 Agent 验收；FAIL 返工，PASS 交付。普通修改不额外建立 Spec。
