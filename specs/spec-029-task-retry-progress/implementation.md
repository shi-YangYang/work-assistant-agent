# Implementation Report

## 实现

- 工作助手显式启用 `tasks/retry`，主模型、授权／答复／报告改写核对和工具共用执行器。默认首次加 3 次重试，退避 1／2／4 秒与小幅抖动；受控临时限流采用 Retry-After。子节点耗尽不触发外层再次重试。
- 节点身份包含输入／冻结模型配置、父节点和逻辑请求身份；工具区分模型消息与调用 ID。Job.result 保存次数、等待时间、内部恢复值与有界历史；最多 96 个节点、512 KB 恢复状态、每节点 8 轮摘要，完成后释放恢复输出。未增加 schema 或迁移。
- 每次尝试复核租约、权限、源输入、业务版本与模型配置。worker 换租约保留已消耗次数，手动重试只重开失败轮；成功结果通过 checkpoint、验证后的内部缓存和业务回执恢复。操作回执重新授权读取，写入与报告入队保持现有幂等约束。
- 逻辑预算为 8 个模型／核对节点及 16 个工具节点，实际调用安全上限为 32 次；Agent 期限 420 秒，worker 总期限 450 秒。每次外部请求独立记录真实用量，未发出的连接失败为 not_sent，超时／中断未知用量不伪造；核对结构无效记录 failed。
- Job DTO／SSE 扩展受控节点摘要，保留 attempt／fence／seq 排序与账号隔离。工作助手消息独立启用黑白灰紧凑进度，支持展开、重试倒计时、就地恢复及完成摘要；前置解析／转写和其它 JobNotice 保持原提示。
- ASR、解析、独立报告 Job 和 Electron 不启用节点重试，HTTP transport 继续 `retries=0`。

## 验证

命令均在专用 `paa_company_test` 数据库及受控模型中执行；日志保存在 `artifacts/spec029/`。

| 命令 | 结果 |
| --- | --- |
| `npm run test:server -- tests/server/test_task_retry.py` | 最终 20 passed：次数／退避、耗尽、父子不放大、权限／输入／业务版本变化、worker 恢复、并行身份、写入与报告入队幂等、真实 harness checkpoint 恢复、逐次真实／未知／未发送／无效核对用量 |
| `npm run test:server -- tests/server/test_model_services.py tests/server/test_recovery.py tests/server/test_operation_recovery.py tests/server/test_assistant_execution.py tests/server/test_business_actions.py tests/server/test_freeform_actions.py tests/server/test_search_metrics_feedback.py tests/server/test_business_assistant.py tests/server/test_architecture.py` | 首轮 170 passed、2 failed；核对错误码／当前配置恢复兼容已修复，中断流旧断言调整为 4 次实际尝试 |
| `npm run test:server -- tests/server/test_task_retry.py tests/server/test_operation_recovery.py::test_review_retry_never_reexecutes_business_even_with_current_config tests/server/test_search_metrics_feedback.py::test_stage_feedback_precedes_reviewed_reply_and_preserves_usage tests/server/test_model_services.py` | 上述回归失败均通过；本轮 66 passed、1 failed，唯一失败为新增报告测试缺少已确认工作，已补真实测试工作，最终定向测试通过 |
| `npm run test:server -- tests/server/test_task_retry.py::test_report_enqueue_receipt_is_not_repeated_or_report_completion tests/server/test_task_retry.py::test_unsent_connection_failures_are_not_reported_as_actual_calls tests/server/test_report_reliability.py` | 24 passed，包含独立报告不增加重试的兼容验证 |
| `npm run test:server -- tests/server/test_task_retry.py::test_malformed_authorization_retries_without_inventing_successful_usage tests/server/test_task_retry.py::test_harness_manual_resume_only_retries_failed_model_after_committed_tool tests/server/test_model_services.py::test_actual_bounded_harness_uses_frozen_service_and_reserves_each_call tests/server/test_report_reliability.py::test_structured_report_actual_request_usage_and_report_probe` | 8 passed，覆盖核对校验接入逐次用量后的相关路径 |
| `npm run test:web` | 32 files／189 tests passed |
| `npm run test:web -- tests/web/task-progress.test.ts` | 前置阶段兼容调整后 4 passed |
| `npm run typecheck:web` | passed |
| 修改的 Web／契约／Web 测试文件运行 Prettier；修改的 Web／Web 测试文件运行 ESLint；`git diff --check` | passed |

## 限制与交接

- 服务商可能已执行超时请求，自动重试不能保证外部只计费一次；逐次用量按真实返回／未知状态保留。
- 确定性业务拒绝、无权限、配置错误和未知异常不自动重试。业务版本变化要求重新提问以获取最新内容。
- 未运行桌面测试、全仓构建／Lint、真实 ASR 或生产操作；未 commit／push，未查询远端 CI。
- 真实本地模型流程与浏览器视觉检查由协调 Agent 完成；本报告不替代独立验收。

## 回执恢复修正

- 业务回执引用与对应写入在同一事务提交；节点恢复先重新授权读取该回执，恢复本次写出的准确版本，再核对全部读取版本。外部修改／删除、权限、源输入和模型配置变化仍拒绝恢复。
- 读取已提交结果先于尝试预算和退避，不增加尝试次数、不重新调用授权／报告事实模型、不重写或重新入队；第 4 次提交后响应异常与 worker 中断均可恢复。
- `npm run test:server -- tests/server/test_task_retry.py tests/server/test_task_receipt_recovery.py artifacts/spec029/test_acceptance_recovery_probe.py`：**37 passed**。包含原失败探针、七种业务动作的第 4 次提交中断、更新工作／报告的外部版本与删除冲突，以及权限／输入／配置／其它读取版本变化。
- 首轮同批运行 `tests/server/test_architecture.py`，总计 **49 passed**；之后只调整执行器对第 4 次响应异常的回执优先处理，以上 37 项再次通过。Python 不在现有 Prettier 覆盖范围；本次 diff 检查通过，未重跑 Web、桌面或真实模型。独立验收结论见 [验收报告](acceptance.md)。

## 本地真实验证

使用现有账户与模型配置，通过浏览器完成创建（6.52 秒）、查询（8.75 秒）和修改（14.99 秒）。创建与修改各只有一条成功回执，修改仅增加一个版本；刷新保留节点，临时业务数据已清理。浅／深色、390px／1280px及键盘展开已检查。故障恢复采用专用测试库注入，不对真实模型制造重复失败。证据位于 `artifacts/spec029/real-verification.md` 和对应截图／JSON。
