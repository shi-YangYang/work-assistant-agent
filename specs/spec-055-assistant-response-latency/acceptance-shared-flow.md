# 共享主流程独立验收

## Result

FAIL

共享主流程存在一项可复现的任务状态回归：工具额度拒绝已知步骤后，普通正文终态仍将任务保存为完成。真实模型与浏览器取证仍由协调 Agent 汇总；本结论不把先前传输验收 PASS 当作本轮通过。

## Issues

### P1：预算封口后的普通正文丢失已知未完成项

`runtime/middleware.py` 在探索额度临界时移除全部工具并要求直接答复，超过工具节点上限时只返回 `unavailable`，没有将被拒绝步骤写入任务状态。`completion/prose.py` 未找到显式或授权任务解释时构造默认 `completed`，导致已知未执行步骤从终态和后续任务上下文消失。

独立复现使用实际 worker/graph、PostgreSQL 独占测试 schema 和固定模型，发送十八个独立查询；模型第二次调用遵循本轮 `tools=[]`，返回合法普通正文“最后两次查询未执行”。实际仅有 16 个工具节点，最终 `taskOutcome.state=completed`、`remaining=[]`、`incompleteTask=false`。没有调用真实模型或改动业务源码。

现有 `test_parallel_tool_batch_exhaustion_still_delivers_without_raising_budget` 的固定模型在 `tools=[]` 时仍调用旧 `finish_task` 并填写 `blocked`，因此其通过不能验证新普通正文路径。

证据：[复现脚本](../../artifacts/spec055/shared-flow/acceptance/test_budget_prose.py)、[失败日志](../../artifacts/spec055/shared-flow/acceptance/budget-prose.log)、[真实保存结果](../../artifacts/spec055/shared-flow/acceptance/budget-prose-result.json)。单项定向检查结果为 **1 failed，3.40s**；独占 schema 已清理。

## Spec Coverage

- 普通正文与业务共用精简主提示和 `auto`；正常正文不额外包装，标记可选，旧 Delivery/checkpoint 保留读取。
- 分片标记、重复键、非法结构、工具前说明、晚到工具撤回、团队来源与取消仍进入既有候选/来源/撤回链路；复用通过的子系统检查。
- 数值篇幅沿用全文计数、用户原文引用和标题排除，767 字仍触发有界修复。复杂指令依赖模型显式声明的既有边界保留，没有全局审稿。
- 状态工具不产生业务回执，和业务写入同批时拦截；来源引用、授权、版本、幂等与实际操作回执路径未被绕过。显式未完成项和无关聊天保留旧待办已有覆盖，但上述预算封口例外必须修复。
- 五项测试的旧审稿假设在冻结 before 同样失败；改写后仍保留部分完成、同一回执/对象幂等、定向正文修复和不重复写入断言，没有以删断言掩盖本轮回归。另有上列额度测试需要改为真实新输出形式。

## Tests

复用 [实施日志目录](../../artifacts/spec055/shared-flow/implementation/)：`targeted-v3` 90 passed、`streams-redis` 55 passed、`completion-contract-v2` 33 passed、`final-edges` 26 passed。组间有交叉，不合计为独立用例数。初测 162 passed / 14 failed 中九项缺隔离 Redis，五项沿用旧审稿假设，分别有补验和冻结 before 对照证据。

独立验收只追加上述已定位缺口的单项复现，未重跑已通过检查、全仓库测试、构建、真实模型或日常服务。未提交、推送或查询远端 CI。

## Regression Risks and Evidence Limits

- 普通聊天 `job.state=awaiting_input` 是本轮前已存在的队列状态；完整正文的 `phase=complete`、`taskOutcome.state=completed` 才是语义完成证据，不应单凭该队列值判性能失败。
- 冻结四组真实模型与浏览器结果尚未全部纳入本报告，不能据此宣称最终性能通过或稳定降幅。
- 创建→续聊修改验证业务链；同条请求两个独立业务动作宜另以一次固定 after 样本补充，不加入冻结对照的收益计算。

## Required Rework

在实际预算拒绝/封口处持久记录已知未执行步骤，并让普通 Delivery 使用该受控状态，保证剩余项和后续承接不丢失；不能从自由正文猜状态、增加全局审稿或提高额度。将定向用例改为确实返回普通正文，断言预算不变、未完成不标成功，已成功业务回执不重放。修复后由新的独立 Agent 验收。
