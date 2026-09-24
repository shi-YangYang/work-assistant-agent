# Specs

[Spec 001～025 摘要](history-001-025.md)

| Spec | 内容 | 状态与验证 |
| --- | --- | --- |
| [026](spec-026-web-design-refresh/spec.md) | Web 黑白灰设计、助手交互与响应式 | 已实施；[验收 PASS](spec-026-web-design-refresh/acceptance.md) |
| [027](spec-027-desktop-design-refresh/spec.md) | Electron 黑白灰设计、全屏画布与会议交互 | 已实施；[macOS 验收 PASS，Windows 未实测](spec-027-desktop-design-refresh/acceptance.md) |
| [028](spec-028-company-backend-architecture/spec.md) | 公司后端迁入 apps/server，拆分业务模块与 harness | [验收 PASS](spec-028-company-backend-architecture/acceptance.md) |

## 文档分工

- 历史摘要：每个 Spec 简述做了什么，原始细节可从 Git 查阅。
- `spec.md`：需求、边界、验收标准。
- `plan.md`：实施步骤和必要验证。
- `acceptance.md`：实际验收结果、证据与未解决问题。

## 生命周期

新 Spec 从 **029** 继续，使用 `spec-XXX-short-name/` 和 [_template](_template/)。主 Agent 确认需求后，由实施 Agent 开发、独立 Agent 验收；FAIL 返工，PASS 交付。普通修改不额外建立 Spec。
