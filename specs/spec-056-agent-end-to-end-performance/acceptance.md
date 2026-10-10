# Acceptance

## Result

**FAIL**。流式模型连接复用未生效；完整性能与质量配对尚未完成。以下受控检查通过不代表 Spec 整体验收通过。

## Spec Coverage

- 已审查基于 `3d0a0d1` 的连接复用、结构化引用预置工具组、文档与文件有界并行、任务关联计时变更。
- 连接池按任务、origin、允许来源列表划分，请求客户端独立持有 Cookie／Authorization；新连接保留全 DNS 结果检查和数字 IP 连接。未发现这部分引入越权或凭证共享。
- 文档解析保留租约、归属、摘要与提取版本检查，worker 内解析并发为 2；文件下载并发为 2，保持输入顺序，完整下载后再校验来源、版本、配额与发布事务。
- 工具组预置只使用本条消息的文档及有效工作引用，不授予执行权限；工具的原有角色、来源、授权及幂等边界保留。
- 计时增加父子调用、网络阶段和排队观测；不记录请求正文、密钥或隐藏推理。最终关键路径与浏览器完整可用时间仍须结合真实证据核对。

## Tests

独立补充检查 **148 passed，64.02 秒**，无外部模型请求。覆盖 `test_builtin_execution`、`test_assistant_memory`、`test_deliverables`、`test_work_materials`、`test_work_record_tool_access`、`test_business_actions`、`test_business_assistant`、`test_agent_virtual_files`、`test_assistant_interactions`、`test_prose_delivery`，以及成员目录分页单例。

- [执行日志](../../artifacts/spec056/acceptance/coverage.log)
- [精确测试节点与结果](../../artifacts/spec056/acceptance/coverage.xml)
- [隔离环境与清理记录](../../artifacts/spec056/acceptance/coverage-result-corrected.json)

初次建表因测试连接参数空格编码失败，未运行测试；改用正确 URI 编码后在新 schema 执行。原失败保留，两次自建 schema 均已删除。未重复运行实施阶段已通过的工具目录、文档及权限检查。

实施阶段已有 `model_services` 四个参数组合期望调用 4 次、实际 3 次的失败；基线复现证据仅对应其中一个组合。本轮未将这些失败计为通过，也未重复执行。

## Issues

### P2：标准流式响应没有复用模型连接

`apps/server/app/integrations/models/chat.py` 在收到 `[DONE]` 后立即退出 `aiter_lines()`；HTTP 响应结束帧尚未消费，关闭响应时连接被关闭。`task_connections()` 因而无法复用该连接。

独立受控复现使用正常 HTTP/1.1 chunked SSE，所有响应包含完整正文、`finish_reason=stop`、`[DONE]` 和 HTTP 结束帧。同一任务四次成功的 `streaming=True` 请求产生 **4 条 TCP 连接、4 次请求**，不是预期的 1 条连接。

- [首次结果](../../artifacts/spec056/acceptance/stream-reuse.json)
- [复现脚本](../../artifacts/spec056/acceptance/stream_reuse_probe.py)：`PYTHONPATH=apps/server .venv-server/bin/python artifacts/spec056/acceptance/stream_reuse_probe.py`

现有连接数 4→1 的受控测试只验证非流式路径，不能推导主流式请求收益。修复不得通过无界等待响应尾部延长用户任务或绕过响应大小、超时和取消保护。

### 全流程验收证据尚未完成

- 真实前后配对、离线质量、失败率、各阶段与完整成果耗时尚未汇总，不判定 20% 目标或质量不退步已经满足。
- 工作引用预置工具组的真实旅程目前每版仅一次，不能用于稳定中位数结论。若补充重复采样，须先冻结计划并保留原始样本。
- 工具覆盖映射仍需核对 `finish_task` 旧协议的实际执行、`propose_progress` 成功路径和 `web_fetch` 失败／权限边界。可复用已有明确通过证据；没有证据时定向检查对应模块。存在测试文件或仅断言工具名称不算执行覆盖。
- 报告子作业 API 就绪、报告正文浏览器可见、普通答案最终呈现需要分别记录，不能混用。

## Regression Risks

受控检查暂未发现新增越权、重复业务写入或部分文件发布。真实模型质量波动、网络错误和长任务结果仍未完成判断；不能把测试通过等同于全部真实流程无回归。

## Required Rework

1. 修复流式响应的有界连接回收／复用，或撤回这项无流式收益的优化及相应收益主张；以真实流式协议验证关闭、超时、取消和尾部异常。
2. 由新的独立验收 Agent 验证返工，只补充相关新改动与上述具体覆盖缺口，保留已经通过的 148 项证据。
3. 在最终源码上完成冻结配对、成果核验和离线质量评审；分别报告实际收益、未达到目标、既存问题与外部限制，再决定整体验收结果。
