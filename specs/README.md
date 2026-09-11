# Specs

| Spec | 范围 | 状态 | 验收 |
| --- | --- | --- | --- |
| [001](spec-001-product-and-technical-foundation/spec.md) | 产品、技术与桌面骨架 | DONE | [PASS](spec-001-product-and-technical-foundation/acceptance.md) |
| [002](spec-002-meeting-recording-and-storage/spec.md) | 麦克风录音、保存与回放 | DONE | [PASS](spec-002-meeting-recording-and-storage/acceptance.md) |
| [003](spec-003-local-transcription/spec.md) | 模型准备、持续转写与恢复 | DONE | [PASS](spec-003-local-transcription/acceptance.md) |
| [004](spec-004-meeting-minutes/spec.md) | API 管理、会后纪要与重试 | ACCEPTANCE | [工程缺陷已关闭，待外部验证](spec-004-meeting-minutes/acceptance.md) |
| [005](spec-005-desktop-distribution-and-controls/spec.md) | 内置运行时打包、设置折叠、暂停录音与播放器 | ACCEPTANCE | [许可缺陷已关闭，待平台／交互验证](spec-005-desktop-distribution-and-controls/acceptance.md) |

录音／ASR 实录结果见 [Spec 003 验证记录](spec-003-local-transcription/verification.md)，纪要与最新工程检查见 [Spec 004 实施报告](spec-004-meeting-minutes/implementation.md)。旧 Spec 的报告保留当时验证范围，不代表当前产品仍停留在旧状态。

## 文档分工

- `.ai/decisions/`：为什么选这个方案、否决了什么、有哪些长期约束；不复制运行日志。
- `spec.md`：目标、行为、边界和验收标准；通过引用使用已有技术决策。
- `plan.md`：模块、数据流、实施顺序、迁移和针对性验证方案；不重抄需求。
- `implementation.md`：最终实现摘要、必要实现细节和已关闭的返工记录。
- `acceptance.md`：独立验收结论、覆盖、证据来源和未验证项；不能由实施者自评替代。
- `verification.md`：仅在有较多实测数据时使用，集中样本、参数、计时与 CI 证据；其他文档引用它。

每条事实只在职责最匹配的位置详述。短 Spec 按模板简写，已写清的内容不为填章节反复展开；已完成返工合入实施 / 验收记录，不为每次 CI 调整永久增加一份重复报告。

## 生命周期

目录用 `spec-XXX-short-name/`。协调 Agent 起草决策并轻量自查，交用户审查，不安排决策子 Agent 或独立验收。关键决策确认 → 实施 Agent 开发 → 新的独立验收 → PASS 交付；FAIL 记录具体问题，交新的实施 Agent 返工，再由新的独立验收 Agent 检查。不开 Spec 的修改由协调 Agent 直接完成。具体遵循 [Spec 工作规则](../.ai/rules/spec-decision-workflow.md) 及 AGENTS.md 的验证 / 停止和分支收尾规则。

## 历史记录

2026-09-10 按用户要求整理：保留编号、需求、历史 PASS / FAIL、修复依据及证据，把已结束的分轮报告归并到各 Spec 的实施摘要与验收记录。本次仅整理文档，没有重新运行测试或改变验收结论。整理前完整原文可在 [Git 快照 23ba685](https://github.com/shi-YangYang/work-assistant-agent/tree/23ba685f5af58039ec30297d8e20af91eef61f10/specs) 查阅，也可用 `git show 23ba685:specs/<目录>/<原文件>` 恢复。
