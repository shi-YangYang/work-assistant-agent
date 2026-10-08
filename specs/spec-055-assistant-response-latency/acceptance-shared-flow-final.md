# 共享主流程与按需工具独立验收

## Result

FAIL

上一轮工具预算拒绝丢失未完成项的问题已关闭。新的独立审查发现：上下文压缩复用主模型时，其内部摘要会进入用户正文发布通道。该问题有不调用真实模型、数据库或 Redis 的适配器层复现，须修复后重新独立验收。

真实 AFTER2 HTTP／worker 对照、双创建、人设和浏览器结果由协调 Agent 汇总，本报告尚未据此给出性能通过结论；此前传输验收 PASS 不覆盖此项回归。

## Issues

### P1：内部上下文压缩摘要被发布为用户正文

`runtime/model.py` 的 `is_reply` 将 `_completion_validator` 视为答复标志。`harness.py` 给主 `BoundedChatModel` 始终配置该校验器，而 `ContextCompaction.summarize()` 复用此模型调用；其活动节点为 `compaction`，不带工具，也未设置 `_verification`。因此内部压缩仍会创建 `ReplyPublisher` 和 `ReplyCandidate`。`allows_reply_stream()` 对压缩消息默认允许预览，`ReplyCandidate.finish()` 最终将没有标记的内部摘要以 `finalizing` 写入用户正文通道。

最小复现直接调用真实 `ContextCompaction.summarize → BoundedChatModel._agenerate/_single → ReplyCandidate`，只替换模型 IO、数据库 IO 和发布器为可观察桩。模型返回“内部压缩摘要：用户尚未完成的目标与历史资料。”后，发布器实际收到同一文本、`state=finalizing`、`force=True`，违反“内部压缩不应发布用户答案”的断言。没有通过伪造用户答复或跳过适配器构造这一结果。

证据：[复现脚本](../../artifacts/spec055/shared-flow/acceptance/test_compaction_preview.py)、[失败日志](../../artifacts/spec055/shared-flow/acceptance/compaction-preview.log)。**1 failed，1.04s**。本复现证明错误内容到达正文发布接口；没有把发布器桩称为真实浏览器泄露取证。

## Spec Coverage

- 目录覆盖断言包含全部现有允许工具及管理员工具，保留旧 `finish_task` 注册但不初始展示。普通请求只有 `load_tools`，加载后提供完整 schema 与专项规则；文件执行关闭时仍可从 documents 发现历史执行读取。
- 公司、用户、job、输入／材料／工作引用、模型配置和节点 scope 进入目录状态标识。加载经现有租约事务和行锁串行更新；同任务幂等，新 scope 不复用。旧 checkpoint 调用隐式登记能力后仍走原 ACL、来源、版本、授权与工具节点，加载后／写入后崩溃恢复测试保留恰好一次写入断言。
- `ToolBoundary` 位于 `ContextCompaction` 外层，先筛选工具并追加专项规则，压缩估算看到实际发送的 schema。加载不创建工具节点、不占 16 步额度，但后续模型请求和时间仍有原上限；未提升预算。
- 上轮预算问题由 `ToolBudgetExceeded` 与 `nodeExecution.budgetBlockedTools` 修复。普通正文和旧 Delivery 的最终评估都合并受控未执行项，真实回执快捷完成不能掩盖拒绝。18 次读取仅执行 16 次、保留两项 blocked；有成功写入时为 partial；14／16 次全部执行仍 completed；同 scope 恢复保留，新输入 scope 清除。
- 新预算替身确实先加载能力，最后遵守 `tools=[]` 返回普通正文；包含不在正文声明遗漏的分支，状态来自服务端拒绝记录。没有继续用不可见的 `finish_task` 代替新路径。
- 新普通正文仍校验内部标记、原文篇幅引用和实际长度；767 字继续触发有界定向修复。工具前说明、同批混合调用、晚到工具撤回、团队来源与取消沿用现有候选和来源边界；上述压缩入口是本轮新发现的例外。
- 旧测试调整保留真实记录／回执身份、部分完成、未完成项和不重复写入等有效断言。文件能力发现测试以 `taskOutcome=completed`、完整答复和没有业务动作判断完成；没有将此前已存在的队列 `awaiting_input` 当作用户等待。

## Tests

实施检查采用 S3 的相关子系统范围，复用原始日志和断言，不重复已通过检查：

- [目录组](../../artifacts/spec055/shared-flow/catalog/catalog-v1.log)：26 passed、51 deselected，20.49s。
- [相邻组初测](../../artifacts/spec055/shared-flow/catalog/adjacent-v1.log)：42 passed、3 failed，15.34s。三项失败来自能力发现替身仍按业务写入的队列状态判断；[定向修正及压缩／记忆检查](../../artifacts/spec055/shared-flow/catalog/adjacent-v2.log)为 9 passed，5.66s。
- [预算初测](../../artifacts/spec055/shared-flow/budget-rework/targeted.log)为 5 failed、2 passed；[失败项修正后检查](../../artifacts/spec055/shared-flow/budget-rework/targeted-v2.log)为 5 passed、35 deselected，8.62s。最终目录组再次覆盖目录适配后的预算路径，不将初测日志表述为全部通过。
- 前轮共享主流程的 90 项交付／篇幅、55 项流式、33 项交付契约与 26 项边界检查见[前轮验收](acceptance-shared-flow.md)及其原始日志；与本轮组间有交叉，不合计为独立用例数。
- 独立验收仅追加上述具体缺口的一个最小复现，未跑全项目测试／build／lint／typecheck，未调用真实模型或操作用户服务与日常数据，未修改业务源码、提交、推送或查询远端 CI。

## Regression Risks and Evidence Limits

当前复现使用实际适配器和候选解析，但发布端为观察桩，不证明浏览器实际展示时长。最终主模型四组对照、人设、双创建与浏览器证据尚待协调 Agent 汇总；原 first after 对照的作文 182.02 → 188.91 秒、续聊修改 258.26 → 334.35 秒、创建 96.66 → 14.13 秒必须保留，不据单项收益宣称整体稳定提速。请求层 44.90 秒探测仅为可行性证据。

## Required Rework

明确区分用户答复和内部模型调用，禁止上下文压缩摘要进入 `ReplyPublisher`。同时保留正常普通正文，以及工具预算封口后 `tools=[]` 的普通正文交付与预览，不能简单恢复“必须带 tools 才能预览”。增加适配器层针对性验证，再由新的独立 Agent 验收；已有业务、目录和传输通过项无需无理由重跑。
