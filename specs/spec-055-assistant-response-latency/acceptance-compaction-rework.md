# 上下文压缩隔离返工独立验收

## Result

FAIL

分块摘要调用已与用户正文隔离；多块摘要合并调用仍遗漏隔离标记，可以把内部摘要交给正文发布器。此结论仅针对最新 compaction 修复，复用前轮已通过的目录、工具预算、交付与流传输结果，不重验其他子系统。

## Issues

### P1：多块摘要合并仍进入用户正文通道

`apps/server/app/agent/context/compaction.py:111` 仅在循环中的单块摘要调用前设置 `internal_call_kind`，并于该次调用后复位。当 `len(summaries) > 1` 且合并长度超过 `target` 时，第 124 行的第二处 `self.model.ainvoke(prompt)` 已不在隔离作用域中。主模型仍携带正文校验器，`BoundedChatModel._single()` 因而创建发布器及候选，并对内部合并摘要执行正文校验和发布。

独立复现沿用上一轮的真实 `ContextCompaction → BoundedChatModel → ReplyCandidate`，仅增加历史输入长度并设置较小摘要目标以触发合并分支。模型、数据库和发布 IO 为可观察替身。发布器实际收到内部摘要，参数为 `state=finalizing`、`force=True`。这证明错误内容到达正文发布接口，不把发布器替身称为真实浏览器泄露证据。

证据：[多块合并复现](../../artifacts/spec055/shared-flow/acceptance/test_compaction_merge_preview.py)、[失败日志](../../artifacts/spec055/shared-flow/acceptance/compaction-merge-preview.log)。

## Tests

- 复用实施者的[定向日志](../../artifacts/spec055/shared-flow/compaction-rework/targeted.log)：3 passed，3.25s；覆盖原单块复现、共享模型并发的普通正文／压缩路径，以及预算受限正文的回执不重放。
- 独立审查确认 `ContextVar` 不改共享模型属性，正常分块调用保留预算、时限和用量，内部计时归 `compaction`，普通 `tools=[]` 回复仍可预览及校验。
- 仅对新发现的合并分支运行一次定向检查：`pytest artifacts/spec055/shared-flow/acceptance/test_compaction_merge_preview.py -q --tb=short`，**1 failed，1.07s**。未重复已通过测试，未运行全量测试、构建、Lint 或类型检查。
- 未修改业务代码，未调用真实模型、数据库或 Redis，未操作日常服务，未提交、推送或查询远端 CI。

## Regression Risks and Evidence Limits

当前修复未覆盖全部压缩模型入口，因此不能宣称压缩摘要与用户正文已完整隔离。真实性能与浏览器取证由协调 Agent 汇总；本报告不给出最终性能结论。AFTER2 冻结源码与这次压缩入口修复存在差异，即使基准未触发压缩，也不能将其称为最终全源码的真实模型测试。

## Required Rework

对分块摘要和最终合并摘要的所有模型调用统一应用内部调用隔离，并保证异常／取消时复位。补充多块合并的适配器层回归，继续保留普通 `tools=[]` 回复的发布与正文校验，以及预算、时限、用量和 compaction 计时。修复后由新的独立 Agent 验收，无需重跑已通过的无关工程检查。
