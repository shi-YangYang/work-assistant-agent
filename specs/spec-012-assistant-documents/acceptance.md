# Acceptance — Spec 012

## Result

**PASS · 2026-09-13。** 返工后由新的独立验收 Agent 复核删除顺序、owner 锁／租约 fencing 与正式回归断言，首轮 P1 已修复。复用此前未受改动影响的验收证据与返工已通过的删除组；本轮仅更新验收记录，未修改业务代码、操作日常环境、提交或推送。

## Spec Coverage

- R1／R2：七种格式、混合附件、私有原件、独立解析状态与重试、分页定位及会话草稿隔离均有实现与对应证据；检查了真实解析器与资源限制调用链。
- R3：文件工具按当前会话／本人已确认来源授权，真实读取证据校验引用，输入修订约束写回；仅发文件不能直接生成工作建议。
- R4：增量迁移、权限、原文件／分段清理和晚到解析阻止有覆盖；返工补齐运行中任务的待确认建议及衍生回复清理，保留用户原文、其他已确认摘要和无关排队任务。

## Issues

**首轮 FAIL：[P1] 删除前先清空依赖记录，遗留运行中任务的文档摘录；现已关闭。**

首轮实现中，管理员删除来源报告先调用 `invalidate_context(..., sources_changed=True)`，清空相关运行中任务的 `job.result`，随后 `purge_messages` 才从 `documentReads` 查找依赖消息。会话删除存在相同顺序问题。

已复现触发顺序：文档成为已确认工作／报告来源 → 另一会话的运行中任务通过真实 `read_document` 读取该文件 → `propose_progress` 保存待确认建议 → 最终回复尚未写入时，管理员删除来源报告。任务正确变为 `cancelled`，但其消息的 `drafts` 和 `suggestions` 仍包含 `pending` 的文件摘录；此时没有最终引用可供备用匹配。违反 R4 的衍生内容清理要求。

返工后的 [remove_report／remove_conversation](../../src/python/paa_server/deletion.py) 均先调用 `purge_messages` 消费读取证据，再失效剩余上下文。API 的 `target` 从读取删除目标起持有 owner 行锁，真实读取工具、建议写入、最终回复及 `GuardedSaver` 均通过同一 owner 锁上的 `lease` 校验；事务提交前完成依赖清理、fence 递增和上下文清空，晚到写入无法越过旧租约。附件专属任务的失效不提前清空消息任务证据，依赖消息集合在逐一清理前已收集。

## Tests

- 复用[实施记录](implementation.md)中的解析 20 项、PostgreSQL 文档 8 项与既有回归 19 项、Web 17 项及格式／Lint／类型／普通 Web build 结果；未无理由重跑。
- 首轮独立缺口复现：`node scripts/company.mjs test /tmp/test_spec012_acceptance_gap.py`，结果 **1 failed**，失败断言为删除后待确认建议应为空；专用 `paa_company_test` fixture 完成清理，未操作日常资料。该临时复现现已由正式回归替代。
- 返工的相关删除组 **4 passed，6 deselected**，精确命令见[实施记录的来源删除返工](implementation.md#来源删除返工2026-09-13)。独立复核 [test_source_deletion_purges_inflight_document_proposals](../../tests/server/test_documents.py#L232) 两个参数分支：真实解析及读取后调用 `propose_progress`，明确断言删除前尚无最终回复／引用，删除后建议与草稿内容清空、原文件／分段不可用、用户原文与 Work／Report 快照保留、无关任务仍排队，并由旧上下文触发 `LostLease`。既有共享来源／checkpoint 清理和真实解析晚到结果用例同组通过；未发现需追加或重跑检查的缺口。
- 首轮已检查 `artifacts/spec012/ui-result.json`、`daily-sample-result.json` 以及桌面／手机提取截图；本轮复用主 Agent 对七格式发送、草稿、分页、引用弹窗、下载、无效 JSON 重试及日常迁移保留的证据。

## Regression Risks

Windows 仅有 Job Object API 替身检查，未验证 Windows／Linux 部署实机；日常 Web 使用固定模型，未评估真实模型回答质量或容量。未运行 CI、Electron、发行包、OCR 或真实 ASR。

## Required Rework

无。首轮 P1 已按上述证据关闭；日常服务使用更新代码所需的重启由协调 Agent 处理。
