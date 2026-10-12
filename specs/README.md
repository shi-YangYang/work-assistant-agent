# Specs

[Spec 001～050 摘要](history-001-050.md)

## 当前规格

- [Spec 062：Noria 宠物工作状态](spec-062-noria-pet-activity/spec.md) — 已实施并通过独立验收；全页面本人任务状态与双爪打字动画接入，78 项 Web、2 项后端定向测试通过；[状态设计](spec-062-noria-pet-activity/plan.md)、[验收与限制](spec-062-noria-pet-activity/acceptance.md)。

- [Spec 061：项目目录归类与边界整理](spec-061-directory-organization/spec.md) — 已实施并通过独立验收；Web、后端与测试按职责归类，原 2 项日期假设失败已后续修复并定向通过；[目录与迁移](spec-061-directory-organization/plan.md)、[验收与限制](spec-061-directory-organization/acceptance-final.md)。

- [Spec 060：Agent 可靠性专项修补](spec-060-agent-reliability-repair/spec.md) — 原功能验收完成；计划 Schema 与工具说明契约已修复并定向复验，max 对照波动较大，稳定提速仍未验证；[验收与限制](spec-060-agent-reliability-repair/acceptance.md)、[改造目录](spec-060-agent-reliability-repair/plan.md)。

- [Spec 059：Agent 全量测试与工具循环排查](spec-059-agent-comprehensive-testing/spec.md) — 测试交付通过独立验收，产品问题未修复；[测试报告](spec-059-agent-comprehensive-testing/implementation.md)、[问题清单](spec-059-agent-comprehensive-testing/issues.md)、[验收](spec-059-agent-comprehensive-testing/acceptance.md)。

- [Spec 058：Agent 统一任务预算与进度反馈](spec-058-agent-task-budget/spec.md) — 已实施，独立验收通过；统一内部预算、恢复计数与收尾，用户仅看执行进度和结果；[改造计划](spec-058-agent-task-budget/plan.md)、[测试与限制](spec-058-agent-task-budget/implementation.md)、[返工验收](spec-058-agent-task-budget/acceptance-rework.md)。

- [Spec 057：本地启动与容器管理统一](spec-057-local-runtime-consolidation/spec.md) — 已实施并完成本机迁移，保留四个服务，CD 不变；[验收结果与限制](spec-057-local-runtime-consolidation/acceptance-rework.md)。

- [Spec 056：Agent 全流程性能优化](spec-056-agent-end-to-end-performance/spec.md) — 流程减负已实施；系统检查通过，总体性能目标未证实，max 长等待尚未解决；[计划与改造目录](spec-056-agent-end-to-end-performance/plan.md)、[覆盖矩阵](spec-056-agent-end-to-end-performance/test-matrix.md)。

- [Spec 055：聊天搭子响应速度与等待优化](spec-055-assistant-response-latency/spec.md) — 已实施，传输与交付协议简化已验收；low／max 真实计时及质量、网络限制见[实施结果](spec-055-assistant-response-latency/implementation.md)；[实施计划与改造目录](spec-055-assistant-response-latency/plan.md)。

- [Spec 054：Web 全量测试与先验验证](spec-054-web-comprehensive-testing/spec.md) — 已实施与多轮修复；原始成绩保留，剩余模型回答质量限制不再专项修补；[测试计划](spec-054-web-comprehensive-testing/plan.md)、[当前收尾方案与验证](spec-054-web-comprehensive-testing/rework.md#在线收尾简化)。

- [Spec 053：工作助手思考强度与输出限制调整](spec-053-assistant-reasoning-controls/spec.md) — 已实施直接强度配置，独立验收通过；[改造计划与目录](spec-053-assistant-reasoning-controls/plan.md)、[验收报告](spec-053-assistant-reasoning-controls/acceptance.md)。

- [Spec 052：工作助手正文流式输出](spec-052-assistant-streaming-replies/spec.md) — 已完成；[改造计划与目录](spec-052-assistant-streaming-replies/plan.md)、[验收报告](spec-052-assistant-streaming-replies/acceptance.md)。

- [Spec 051：工作助手跨会话记忆](spec-051-assistant-cross-conversation-memory/spec.md) — 已实施，独立验收通过；[改造计划与目录](spec-051-assistant-cross-conversation-memory/plan.md)、[验收报告](spec-051-assistant-cross-conversation-memory/acceptance.md)。

## 文档分工

- 历史摘要：每个 Spec 简述做了什么，原始细节可从 Git 查阅。
- `spec.md`：需求、边界、验收标准。
- `plan.md`：实施步骤和必要验证。
- `acceptance.md`：实际验收结果、证据与未解决问题。

## 生命周期

新 Spec 从 **063** 继续，使用 `spec-XXX-short-name/` 和 [_template](_template/)。主 Agent 确认需求后，由实施 Agent 开发、独立 Agent 验收；FAIL 返工，PASS 交付。仅测试类 Spec 的产品缺陷按其约定报告，不自动修复。普通修改不额外建立 Spec。
