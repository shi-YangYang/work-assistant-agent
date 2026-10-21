# Specs

[Spec 001～074 摘要](history-001-074.md)

## 当前规格

| Spec | 内容 | 状态 |
| --- | --- | --- |
| [075](spec-075-agent-execution-feedback/spec.md) | Agent 执行范围、受阻恢复与用户反馈治理 | 实施中 |

## 文档分工

- 历史摘要：每个 Spec 简述做了什么，原始细节可从 Git 查阅。
- `spec.md`：需求、边界、验收标准。
- `plan.md`：实施步骤和必要验证。
- `acceptance.md`：实际验收结果、证据与未解决问题。

## 生命周期

下一个 Spec 使用 **076**，采用 `spec-XXX-short-name/` 和 [_template](_template/)。主 Agent 确认需求后，由实施 Agent 开发、独立 Agent 验收；FAIL 返工，PASS 交付。仅测试类 Spec 的产品缺陷按其约定报告，不自动修复。普通修改不额外建立 Spec。
