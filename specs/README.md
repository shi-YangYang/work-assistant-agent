# Specs

[Spec 001～050 摘要](history-001-050.md)

## 当前规格

- [Spec 051：工作助手跨会话记忆](spec-051-assistant-cross-conversation-memory/spec.md) — 已实施，独立验收通过；[改造计划与目录](spec-051-assistant-cross-conversation-memory/plan.md)、[验收报告](spec-051-assistant-cross-conversation-memory/acceptance.md)。

## 文档分工

- 历史摘要：每个 Spec 简述做了什么，原始细节可从 Git 查阅。
- `spec.md`：需求、边界、验收标准。
- `plan.md`：实施步骤和必要验证。
- `acceptance.md`：实际验收结果、证据与未解决问题。

## 生命周期

新 Spec 从 **052** 继续，使用 `spec-XXX-short-name/` 和 [_template](_template/)。主 Agent 确认需求后，由实施 Agent 开发、独立 Agent 验收；FAIL 返工，PASS 交付。普通修改不额外建立 Spec。
