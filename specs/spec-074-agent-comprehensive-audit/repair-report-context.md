# 报告回执续接上下文修复

## 根因与改动

首轮修后真实对照中，T29-low 提交后的模型输入只包含 `submit_report / succeeded / objectRevision`。虽然 API 的同一操作卡已经携带 `reportSnapshot`，`message_reference` 的历史投影白名单却将它丢弃，确认续接因此看不到报告实际栏目。原始证据位于 `artifacts/spec074/20261017-repair-comparison/after/trace.jsonl`，任务 `8da981ee-3621-45e2-912f-dce9e2c28aa1`；已提交版本的 `blockers` 为空，回答却说包含聊天里讨论的四项风险。

- `modules/conversations/references.py` 保留经过 `action_dto` 权限检查的有界 `reportSnapshot`，传递实际版本、正式／候选状态、发布版本、四栏摘录、空栏和截断标记，并标记来源为 `business_action_receipt`。不能取得的旧版本或无权限回执明确为 `null`，不拿当前可变报告猜测历史内容。
- `modules/conversations/context/context_store.py` 仅为报告回执的结果指纹增加投影版本，使旧的报告引用（包括已进入摘要的引用）按原有机制增量更新；没有清空整个会话缓存。携带前轮回执的旧引用通过缺少 `reportSnapshot` 字段识别，一次更新后继续复用。
- 摘要覆盖判断对比摘要实际捕获的 `summarySources.result`。否则新回执更新一次之后，会被误认为已写进旧摘要，下一轮再次消失。更新过的回执现在持续复用缓存，直到新摘要确实捕获该版本。
- 即时生成／编辑／提交工具、`get_business_actions` 和工具恢复路径原本已经传递完整 DTO，无需另写一套回执流程。已有材料尾注隔离逻辑保留。

## 定向验证

S2：会话引用、历史缓存和报告子系统。

```text
tests/server/agent/context/test_report_receipt_history.py
tests/server/agent/context/test_context_store.py
tests/server/modules/reports/test_report_receipts.py
23 passed in 6.40s
```

新增四例通过真实 API、任务与数据库流程产生报告，覆盖：

1. 报告生成后追问：harness 实际送给模型的消息包含草稿字段与空风险栏。
2. 提交请求 → 等待确认 → HTTP 确认 → 系统续接：harness 实际送给模型的消息包含对应提交版本、空风险栏与发布版本；不是只检查前端 DTO。
3. 旧投影增量恢复后连续读取两次，仅报告引用重建一次，普通历史不重建。
4. 旧摘要的陈旧结果不能遮掉更新回执，连续后续读取仍可获得真实字段，并复用缓存。

这里使用可控模型记录实际输入，两个 harness 场景各只发生一次主模型请求；不将其宣称为真实供应商准确率验证。新的 T29 low/high 真实复验由协调任务执行，第一轮失败证据不覆盖。

测试在带所有权标记的本地 `paa_company_test` 独占 schema 执行，schema 和私有目录已清理；环境元数据见 `artifacts/spec074/20261017-report-context-tests/environment.json`。相关 diff 空白检查通过。Python 文件不在当前项目 Prettier 覆盖范围。

## 开销与边界

没有增加模型核对、工具轮次、报告保存步骤或每轮数据库查询。旧报告引用首次使用时按既有按消息重建路径更新一次；普通问答与后续缓存命中路径不变。报告字段仍使用现有每栏最多 240 字的回执摘录，不重复加入整份报告。

本修复使真实证据到达模型，不会从聊天文本擅自写入风险，也不能保证模型总会遵循证据。没有更改权限、报告来源规则、持久化结构、预算或模型强度。未 commit、push。
