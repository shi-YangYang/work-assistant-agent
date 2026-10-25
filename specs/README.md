# Specs

[Spec 001～074 摘要](history-001-074.md)

## 当前规格

| Spec                                             | 内容                                   | 状态   |
| ------------------------------------------------ | -------------------------------------- | ------ |
| [075](spec-075-agent-execution-feedback/spec.md) | Agent 执行范围、受阻恢复与用户反馈治理 | 实施中 |
| [076](spec-076-agent-decision-flow/spec.md)      | Agent 及时澄清、探索收束与上下文精简   | 系统修复完成；模型表现限制见验收 |
| [077](spec-077-report-period-regeneration/spec.md) | 汇报周期展示与删除后主动重新生成 | 独立验收 PASS，未部署 |
| [078](spec-078-remove-daily-reports/spec.md) | 移除日报功能，仅保留周报 | 独立验收 PASS；未执行真实用户库迁移或部署 |
| [079](spec-079-report-source-validation/spec.md) | 工作修改记录与内部修订分离、报告程序校验及真实模型验收 | 阶段 A／B 系统实现独立验收 PASS；保留模型限制及未覆盖入口，全产品扩展未完成 |
| [080](spec-080-recent-changes-real-workflow-regression/spec.md) | 最近变更的完整回归与真实流程验收 | 实测及独立验收完成：FAIL，保留产品失败、未决与未覆盖项；隔离服务及数据已清理 |

## 文档分工

- 历史摘要：每个 Spec 简述做了什么，原始细节可从 Git 查阅。
- `spec.md`：需求、边界、验收标准。
- `plan.md`：实施步骤和必要验证。
- `acceptance.md`：实际验收结果、证据与未解决问题。

## 生命周期

下一个 Spec 使用 **081**，采用 `spec-XXX-short-name/` 和 [_template](_template/)。主 Agent 确认需求后，由实施 Agent 开发、独立 Agent 验收；FAIL 返工，PASS 交付。仅测试类 Spec 的产品缺陷按其约定报告，不自动修复。普通修改不额外建立 Spec。
