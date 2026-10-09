# Acceptance — 硬截止交付返工

## Result

PASS。首轮发现的持久正文来源校验遗漏和记忆变更屏障遗漏均已修复。原 [FAIL 与复现证据](acceptance.md)保留。

## Spec Coverage

- Redis 新快照、缺失快照及旧 fence 快照最终都经过 `safe_prefix()`：先持久化有效临时快照，再执行记忆屏障与现有 `reply_stream.dto()` 的权限、来源和版本校验。持久正文不再直接晋升为最终答复。
- 工作版本变化、删除或归属变化使旧正文撤回；记忆被编辑、清空或关闭后，旧保存声明也被撤回。正文和 `conversationReply` 不保留失效片段，实际记忆不被重写。
- `persist_snapshot()` 将来源版本冲突 `ProviderError` 作为撤回条件；降级交付不会因为这一异常再次失败。
- 有效前缀仍可交付。失效正文不影响独立有效的文件下载与成功业务回执，不新增模型请求，不重复执行工具或业务写入，不公开内部预算。

## Tests

- 独立复验首轮两个原始失败：`artifacts/spec058/acceptance/test_hard_stop_recovery.py`，**2 passed in 2.74s**。使用专用 `paa_company_test` 隔离租户，未调用真实模型，fixture 自动清理；日志为 `artifacts/spec058/acceptance/hard-stop-rework.log`。
- 审查返工的 27 个不同定向用例最终通过证据：`budget-delivery-rework.log` 与 `budget-delivery-redis-recheck.log`。首次 26 passed、1 failed 是未配置 Redis 导致旧网络中断用例无临时正文；仅该失败在独立 Redis namespace 下复验为 1 passed。
- 新增 22 项交付回归仅替换临时流读取和沙盒传输；没有 mock 被验收的来源、权限、记忆检查。它们使用真实隔离数据库事务、HTTP 消息／下载接口和操作回执，检查失效片段撤回、有效结果保留、模型计数不增加及业务不重放。
- 未重复运行已通过的预算核心、37 项 Web、3 项 Chromium 和四条真实模型前后旅程；沿用首轮验收已审查的对应证据。

## Issues

无本次返工范围内未解决问题。

## Regression Risks

- HEAD 既存 5 项失败仍未修改：3 项旧 `finish_task` 假设、1 项人设长度断言、1 项 `reply_stream ↔ publisher` 静态循环，不表述为通过。
- Redis 跨进程／重启 4 项 opt-in、真实 30 分钟等待及完整混合多轮破坏性旅程未执行。文件保留用例使用固定沙盒回执，本轮未新增真实沙盒执行。
- 本次为定向返工验收，不是全量产品或远端 CI 通过结论；真实模型单次耗时不代表稳定提速。

## Required Rework

无。
