# Acceptance

## Result

FAIL。统一计数、预留和内部反馈路径已接入，但硬截止降级交付缺少两项来源有效性检查，不能按当前实现交付。

## Spec Coverage

- 审查完整业务 diff、新预算模块、模型／工具预占、轮次恢复、截止观察、交付及测试变更。
- 预算预占使用现有租约锁和事务；工具逻辑调用与实际模型请求分开计数，兼容协议重发也预占。scope 变化不清零，手动重试保留业务回执。
- 主模型临时尾消息不进入图输入或固定 system；公开 DTO、SSE、前端没有新增预算字段和组件。
- 受控边界、真实旅程与既有进度测试证据支持限额扩大及正常路径兼容。硬截止下的持久前缀与记忆屏障不满足规格，见下文。

## Tests

- 阅读实施日志：预算／图／交付／恢复相关定向集，四条真实模型前后旅程及 Excel 下载回读，37 项 Web 与 3 项 Chromium 结果；未无理由重跑已通过集合。
- 独立新增两个隔离 PostgreSQL 复现，均失败：`artifacts/spec058/acceptance/test_hard_stop_recovery.py`。不调用真实模型，不触碰日常数据，fixture 自动清理。
- 第一项：`PYTHONPATH=apps/server:tests/server .venv-server/bin/python -m pytest -q artifacts/spec058/acceptance/test_hard_stop_recovery.py`，1 failed；日志 `hard-stop-recovery.log`。
- 第二项：同文件 `-k memory_barrier`，1 failed、1 deselected；日志 `hard-stop-memory.log`。第一项失败后没有重复执行它。

## Issues

### P1：恢复后的持久正文绕过来源校验

位置：`apps/server/app/agent/completion/budget.py:37-39`。

`persist_snapshot()` 在 Redis 快照缺失或失效时直接返回，随后 `deliver()` 只看持久 `replyStream.state == interrupted` 就使用正文。它没有重新验证对应 `replyStreamSource`。

复现：将工作来源从 revision 1 更新到 2，已有 `reply_stream.dto()` 正确把旧片段判为 withdrawn；在 Redis 无快照时调用硬截止交付，旧片段却进入 `message.reply`，随后消息 API 向用户返回该片段。来源已删除或权限失效时同一分支也没有相应验证，不能把持久前缀当作已授权结果。

### P2：硬截止交付绕过记忆变更屏障

位置：`apps/server/app/agent/completion/budget.py:34-52`。

正常交付在 `tasks/processing/handlers.py:357-358` 调用 `memories.service.validate_job()`，降级交付没有此检查。

复现：助手保存“喜欢吃米饭”后，用户手动清空记忆。`validate_job()` 已明确拒绝旧操作结果；硬截止分支仍把 Redis 中“我已记住你喜欢吃米饭。”保存并显示为答复。本次没有重新写回记忆，但向用户交付了已失效的保存声明。

## Regression Risks

- 修复需要同时覆盖 Redis 新快照和 PostgreSQL 已持久化前缀，不能只调用现有 DTO 而遗漏记忆屏障。
- 来源检查失败应撤回对应失效正文，保留仍有效的业务回执／文件和明确未完成范围；不能重做业务、再请求模型或透传内部额度。
- 现有来源版本冲突可能抛出 `ProviderError`，不能只处理 `ValueError`／HTTP 异常而让整个降级交付再次失败。
- HEAD 既存 5 项失败仍按实施报告单独保留：3 项旧 `finish_task` 假设、1 项旧人设长度断言、1 项静态循环；本次验收不把它们称为通过。
- 未独立运行真实 30 分钟、完整混合多轮旅程、Redis 跨进程 4 项 opt-in；不声明全量产品验收通过，也不从单次真实耗时推断稳定提速。

## Required Rework

1. 硬截止交付前验证所有候选正文的来源、权限与版本，包括已经持久化的 interrupted 前缀；失效时清除而非永久保存。
2. 沿用记忆操作的当前有效性屏障；人工修改／清空后不能交付旧保存声明。
3. 把上述两个失败复现转成正式定向回归，补充有效前缀仍能保留、来源失效时其他真实成果不丢失的断言。只运行交付与来源屏障相关范围，再由新的独立验收 Agent 复验。
